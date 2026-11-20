// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	log "github.com/sirupsen/logrus"
)

// A raw upload (an http_upload job with raw_response) sends one fully
// resolved request per file, from job.FileRequests, and hands the host's
// answer back to Python untouched. Python decides what the answer means;
// Go runs no response_parser, resolve_spec or pre_request and substitutes
// no {token}s.

// MaxRawResponseBytes caps the response body a raw upload returns. An upload
// answer larger than this is a host error page, not a result.
const MaxRawResponseBytes = 2 << 20

// RawRetryAfterCap bounds how long a raw upload waits for a host's
// Retry-After before sending again. A variable so tests can shrink it.
var RawRetryAfterCap = 60 * time.Second

var (
	errMissingUploadRequest = errors.New("missing upload request")
	errRawResponseTooLarge  = fmt.Errorf("upload response too large (over %d bytes)", MaxRawResponseBytes)
)

// RawUploadRequest is the resolved request for one file of a raw upload.
// MultipartFields holds exactly one field of type "file", whose value is the
// file's path; every other field is type "text". FormFields are extra text
// fields. All values are sent exactly as given.
type RawUploadRequest struct {
	URL             string                    `json:"url"`
	Method          string                    `json:"method"`
	Headers         map[string]string         `json:"headers,omitempty"`
	MultipartFields map[string]MultipartField `json:"multipart_fields"`
	FormFields      map[string]string         `json:"form_fields,omitempty"`
}

// RawUploadResult is what the host answered.
type RawUploadResult struct {
	Body       string
	StatusCode int
	FinalURL   string
}

// rawUploadParts is a validated request: its text fields in send order and
// its file field's name.
type rawUploadParts struct {
	fileField string
	textNames []string
	text      map[string]string
}

func invalidUploadRequest(format string, args ...interface{}) error {
	return fmt.Errorf("invalid upload request: "+format, args...)
}

func validateRawUploadRequest(fp string, request *RawUploadRequest) (rawUploadParts, error) {
	parts := rawUploadParts{text: map[string]string{}}
	if request.URL == "" {
		return parts, invalidUploadRequest("no url")
	}
	for name, field := range request.MultipartFields {
		switch field.Type {
		case "file":
			if parts.fileField != "" {
				return parts, invalidUploadRequest("more than one file field")
			}
			if filepath.Clean(field.Value) != filepath.Clean(fp) {
				return parts, invalidUploadRequest("file field %q names another file", name)
			}
			parts.fileField = name
		case "text":
			parts.text[name] = field.Value
		default:
			return parts, invalidUploadRequest("field %q has unsupported type %q", name, field.Type)
		}
	}
	if parts.fileField == "" {
		return parts, invalidUploadRequest("no file field")
	}
	for name, value := range request.FormFields {
		parts.text[name] = value
	}
	for name := range parts.text {
		parts.textNames = append(parts.textNames, name)
	}
	// Text fields first, in name order, then the file: some upload scripts
	// read session fields before they accept the file.
	sort.Strings(parts.textNames)
	return parts, nil
}

// rawRefusalCodes are the statuses with which a host refuses an upload
// without taking it ("too many requests", "unavailable"), so a raw upload
// answered with one is sent again. Every other status, 502, 504 and 52x
// included, may come after the host stored the file and goes to Python as
// is. Only the codes the job's retry config also lists are retried.
var rawRefusalCodes = []int{http.StatusTooManyRequests, http.StatusServiceUnavailable}

// rawUploadRetryConfig is the job's retry config with only the refusal codes
// among its retryable statuses.
func rawUploadRetryConfig(job *JobRequest) *RetryConfig {
	config := *retryConfigForJob(job)
	var codes []int
	for _, code := range config.RetryableHTTPCodes {
		if slices.Contains(rawRefusalCodes, code) {
			codes = append(codes, code)
		}
	}
	config.RetryableHTTPCodes = codes
	return &config
}

// retryAfter reads a Retry-After header (seconds or an HTTP date), capped at
// RawRetryAfterCap; ok is false when the header is missing or unreadable.
func retryAfter(header string) (time.Duration, bool) {
	header = strings.TrimSpace(header)
	if header == "" {
		return 0, false
	}
	var wait time.Duration
	if seconds, err := strconv.Atoi(header); err == nil {
		wait = time.Duration(seconds) * time.Second
	} else if at, err := http.ParseTime(header); err == nil {
		wait = time.Until(at)
	} else {
		return 0, false
	}
	return min(max(wait, 0), RawRetryAfterCap), true
}

// ExecuteRawUpload sends fp's resolved request with the upload-attempt
// protections (stall watchdog, bounded response wait, no resend once the
// body was sent) and returns the host's answer whatever its status, except
// that a 429 or 503 refusal is sent again, after the host's Retry-After
// (capped) and the host's rate limit, up to the job's retry count.
func ExecuteRawUpload(ctx context.Context, client *http.Client, fp string, job *JobRequest) (RawUploadResult, error) {
	request := job.FileRequests[fp]
	if request == nil {
		return RawUploadResult{}, errMissingUploadRequest
	}
	parts, err := validateRawUploadRequest(fp, request)
	if err != nil {
		return RawUploadResult{}, err
	}
	if JobHasExplicitRateLimit(job) {
		emitUploadStatus(job, fp, "Waiting")
		if err := WaitForRateLimit(ctx, job.Service); err != nil {
			return RawUploadResult{}, err
		}
	}
	emitUploadStatus(job, fp, "Preparing")

	method := request.Method
	if method == "" {
		method = http.MethodPost
	}
	logger := log.WithFields(log.Fields{"action": "raw_upload", "file": filepath.Base(fp), "url": request.URL})

	send := func() (_ RawUploadResult, _ int, retryAfterHeader string, sent bool, attemptErr error) {
		pr, pw := io.Pipe()
		defer pr.Close()
		writer := multipart.NewWriter(pw)
		go func() {
			_ = pw.CloseWithError(writeRawMultipart(writer, parts, fp, job))
		}()

		// No wall-clock limit on the transfer: the attempt fails when the body
		// stalls or the host stops answering, and a failure after the body was
		// sent is never retried because the host may have stored the file.
		attempt := newUploadAttempt(ctx)
		defer func() {
			attemptErr = attempt.finish(attemptErr)
			sent = attempt.bodySent.Load()
		}()

		req, err := http.NewRequestWithContext(attempt.ctx, method, request.URL, attempt.body(pr))
		if err != nil {
			return RawUploadResult{}, 0, "", false, NoRetry(invalidUploadRequest("%v", err))
		}
		req.Header.Set("Content-Type", writer.FormDataContentType())
		req.Header.Set("User-Agent", GetUserAgent(job.Config))
		for key, value := range request.Headers {
			req.Header.Set(key, value)
		}

		emitUploadStatus(job, fp, "Uploading")
		resp, err := attempt.do(client, req)
		if err != nil {
			return RawUploadResult{}, 0, "", false, err
		}
		defer resp.Body.Close()

		body, err := io.ReadAll(io.LimitReader(resp.Body, MaxRawResponseBytes+1))
		if err != nil {
			return RawUploadResult{}, resp.StatusCode, "", false, err
		}
		if len(body) > MaxRawResponseBytes {
			return RawUploadResult{}, resp.StatusCode, "", false, NoRetry(errRawResponseTooLarge)
		}
		result := RawUploadResult{Body: string(body), StatusCode: resp.StatusCode, FinalURL: request.URL}
		if resp.Request != nil && resp.Request.URL != nil {
			result.FinalURL = resp.Request.URL.String()
		}
		return result, resp.StatusCode, resp.Header.Get("Retry-After"), false, nil
	}

	// One attempt count for transport failures and refusals, as on the
	// legacy path (RetryWithBackoff).
	config := rawUploadRetryConfig(job)
	bodySent := false
	var lastErr error
	var wait time.Duration
	for attempt := 0; attempt <= config.MaxRetries; attempt++ {
		if attempt > 0 {
			if err := waitToResend(ctx, job, fp, wait); err != nil {
				return RawUploadResult{}, err
			}
		}
		result, status, retryAfterHeader, sent, err := send()
		if err == nil {
			if attempt < config.MaxRetries && slices.Contains(config.RetryableHTTPCodes, status) {
				// The host refused the file without taking it: a refused
				// body is not one the host may have kept.
				if delay, ok := retryAfter(retryAfterHeader); ok {
					wait = delay
				} else {
					wait = CalculateBackoff(attempt+1, config)
				}
				emitUploadLog(job, fp, fmt.Sprintf("Host answered HTTP %d to %s; sending it again in %s",
					status, filepath.Base(fp), wait.Round(time.Millisecond)))
				continue
			}
			return result, nil
		}
		bodySent = bodySent || sent
		lastErr = err
		// Transport failures retry as on the legacy path: an answer cut off
		// while it was read counts by its status, and a failure after the
		// body was sent is never retried (attempt.finish).
		if !IsRetryableError(err, status, config) || ctx.Err() != nil {
			break
		}
		if attempt >= config.MaxRetries {
			lastErr = fmt.Errorf("max retries (%d) exhausted, last error: %w", config.MaxRetries, err)
			break
		}
		wait = CalculateBackoff(attempt+1, config)
		logger.WithField("attempt", attempt+1).Info("Raw upload failed, retrying")
	}
	if bodySent {
		return RawUploadResult{}, &bodySentError{err: lastErr}
	}
	return RawUploadResult{}, lastErr
}

// waitToResend waits before sending a raw upload again, then for the host's
// rate limit; it ends early when ctx does.
func waitToResend(ctx context.Context, job *JobRequest, fp string, wait time.Duration) error {
	emitUploadStatus(job, fp, "Waiting")
	timer := time.NewTimer(wait)
	defer timer.Stop()
	select {
	case <-timer.C:
	case <-ctx.Done():
		return ctx.Err()
	}
	if JobHasExplicitRateLimit(job) {
		return WaitForRateLimit(ctx, job.Service)
	}
	return nil
}

// bodySentError marks a failed upload whose whole body reached the host, so
// the host may have stored the file although the upload failed.
type bodySentError struct{ err error }

func (e *bodySentError) Error() string { return e.err.Error() }
func (e *bodySentError) Unwrap() error { return e.err }

// UploadBodySent reports whether a failed raw upload's whole body reached the
// host before it failed.
func UploadBodySent(err error) bool {
	var sent *bodySentError
	return errors.As(err, &sent)
}

// writeRawMultipart writes the text fields, then the file with progress
// events, and closes the multipart body.
func writeRawMultipart(writer *multipart.Writer, parts rawUploadParts, fp string, job *JobRequest) error {
	for _, name := range parts.textNames {
		if err := writer.WriteField(name, parts.text[name]); err != nil {
			return err
		}
	}
	part, err := writer.CreateFormFile(parts.fileField, filepath.Base(fp))
	if err != nil {
		return err
	}
	f, err := os.Open(fp) // #nosec G304 -- validated job file path.
	if err != nil {
		return err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return err
	}
	if _, err := io.Copy(NewProgressWriter(part, info.Size(), fp, job.ID), f); err != nil {
		return err
	}
	return writer.Close()
}

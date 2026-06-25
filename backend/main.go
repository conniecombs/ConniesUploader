// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/http/cookiejar"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	log "github.com/sirupsen/logrus"
	"golang.org/x/time/rate"

	"github.com/conniecombs/GolangVersion/core"
)

const (
	minSidecarWorkers = 1
	maxSidecarWorkers = 16
)

// ---------------------------------------------------------------------------
// Package-level types — aliased from core so existing test files compile
// unchanged.
// ---------------------------------------------------------------------------

type (
	JobRequest         = core.JobRequest
	HttpRequestSpec    = core.HttpRequestSpec
	PreRequestSpec     = core.PreRequestSpec
	MultipartField     = core.MultipartField
	ResponseParserSpec = core.ResponseParserSpec
	OutputEvent        = core.OutputEvent
	RetryConfig        = core.RetryConfig
	RateLimitConfig    = core.RateLimitConfig
	ProgressEvent      = core.ProgressEvent
	ProgressWriter     = core.ProgressWriter
	HTTPUploadResult   = core.HTTPUploadResult
)

// Constant aliases so test files referencing old names continue to compile.
const charset = core.Charset
const DefaultUserAgent = core.DefaultUserAgent

// ---------------------------------------------------------------------------
// Shared HTTP client (package-level so test files can replace it).
// ---------------------------------------------------------------------------

var client *http.Client

func clampSidecarWorkers(workers int) int {
	if workers < minSidecarWorkers {
		return minSidecarWorkers
	}
	if workers > maxSidecarWorkers {
		return maxSidecarWorkers
	}
	return workers
}

func initHTTPClient() {
	jar, err := cookiejar.New(nil)
	if err != nil {
		log.WithError(err).Warn("failed to initialize cookie jar; continuing without persistent cookies")
	}
	client = &http.Client{
		Timeout: core.ClientTimeout,
		Jar:     jar,
		Transport: &http.Transport{
			MaxIdleConns:          100,
			MaxIdleConnsPerHost:   10,
			MaxConnsPerHost:       20,
			IdleConnTimeout:       90 * time.Second,
			ResponseHeaderTimeout: core.ResponseHeaderTimeout,
			ForceAttemptHTTP2:     true,
		},
	}
}

// initScheduler starts the post scheduler with a generic HTTP post function.
func initScheduler() {
	core.InitScheduler(client, scheduledPostFn)
}

// scheduledPostFn executes a scheduled forum post using the generic HTTP runner.
// It performs: GET forum.php → extract security token → POST reply.
func scheduledPostFn(ctx context.Context, httpClient *http.Client, threadID, message string) (bool, string) {
	spec := &core.GenericHttpRequestSpec{
		URL:    fmt.Sprintf("https://vipergirls.to/newreply.php?do=postreply&t=%s", threadID),
		Method: "POST",
		Headers: map[string]string{
			"Referer": "https://vipergirls.to/forum.php",
		},
		UseCookies: true,
		FormFields: map[string]string{
			"message":       message,
			"do":            "postreply",
			"t":             threadID,
			"parseurl":      "1",
			"emailupdate":   "9999",
			"securitytoken": "{security_token}",
		},
		ResponseType:  "html",
		ExtractFields: map[string]string{},
		SuccessCheck: &core.SuccessCheck{
			Field: "__response_body__",
			Match: "(?i)thank you for posting|redirecting",
			Type:  "regex",
		},
		PreRequest: &core.PreRequestSpec{
			Action: "vg_get_token",
			URL:    "https://vipergirls.to/forum.php",
			Method: "GET",
			Headers: map[string]string{
				"Referer": "https://vipergirls.to/forum.php",
			},
			UseCookies:   true,
			ResponseType: "html",
			ExtractFields: map[string]string{
				"security_token": `regex:SECURITYTOKEN\s*=\s*"([^"]+)"`,
			},
		},
	}

	// Wrap spec in a minimal JobRequest.
	job := &core.JobRequest{
		Service:     "vipergirls.to",
		GenericSpec: spec,
	}

	_, err := core.ExecuteGenericRequest(ctx, httpClient, spec, job)
	if err != nil {
		return false, err.Error()
	}
	return true, "Post successful"
}

// ensureInitialized lazily bootstraps the HTTP client.
// Called by handler functions so tests that set client directly still work.
func ensureInitialized() {
	if client == nil {
		initHTTPClient()
	}
}

// ---------------------------------------------------------------------------
// Thin wrapper functions so test files referencing the old monolith names
// continue to compile without modification.
// ---------------------------------------------------------------------------

func sendJSON(v interface{}) { core.SendJSON(v) }

func getRateLimiter(service string) *rate.Limiter { return core.GetRateLimiter(service) }

func updateRateLimiter(service string, cfg *core.RateLimitConfig) {
	core.UpdateRateLimiter(service, cfg)
}

func waitForRateLimit(ctx context.Context, service string) error {
	return core.WaitForRateLimit(ctx, service)
}

func getJSONValue(data map[string]interface{}, path string) string {
	return core.GetJSONValue(data, path)
}

func randomString(n int) string { return core.RandomString(n) }

func quoteEscape(s string) string { return core.QuoteEscape(s) }

func getDefaultRetryConfig() *core.RetryConfig { return core.GetDefaultRetryConfig() }

func extractStatusCode(err error) int { return core.ExtractStatusCode(err) }

func retryWithBackoff[T any](
	ctx context.Context,
	config *core.RetryConfig,
	fn func() (T, int, error),
	logger *log.Entry,
) (T, error) {
	return core.RetryWithBackoff(ctx, config, fn, logger)
}

func NewProgressWriter(w io.Writer, totalBytes int64, filePath string) *core.ProgressWriter {
	return core.NewProgressWriter(w, totalBytes, filePath)
}

// doRequest wraps core.DoRequest using the package-level client.
func doRequest(ctx context.Context, method, urlStr string, body io.Reader, contentType string) (*http.Response, error) {
	return core.DoRequest(ctx, client, method, urlStr, body, contentType)
}

// executeHttpUpload wraps core.ExecuteHttpUpload using the package-level client.
func executeHttpUpload(ctx context.Context, fp string, job *JobRequest) (string, string, error) {
	return core.ExecuteHttpUpload(ctx, client, fp, job)
}

func executeHttpUploadWithData(ctx context.Context, fp string, job *JobRequest) (HTTPUploadResult, error) {
	return core.ExecuteHttpUploadWithData(ctx, client, fp, job)
}

// rateLimiters and rateLimiterMutex mirror core's exported vars so stress
// tests that reference them by name continue to compile.
var (
	//nolint:unused // Kept for stress tests that reference package-level limiter state.
	rateLimiters = core.RateLimiters
	//nolint:unused // Kept for stress tests that reference package-level limiter state.
	rateLimiterMutex = &core.RateLimiterMutex
)

// ---------------------------------------------------------------------------
// Logger init
// ---------------------------------------------------------------------------

func init() {
	log.SetFormatter(&log.JSONFormatter{
		TimestampFormat: "2006-01-02 15:04:05",
		FieldMap: log.FieldMap{
			log.FieldKeyTime:  "timestamp",
			log.FieldKeyLevel: "level",
			log.FieldKeyMsg:   "message",
		},
	})
	log.SetOutput(os.Stderr)
	log.SetLevel(log.InfoLevel)
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

func main() {
	workerCount := flag.Int("workers", 8, "Number of worker goroutines")
	flag.Parse()
	clampedWorkerCount := clampSidecarWorkers(*workerCount)
	if clampedWorkerCount != *workerCount {
		log.WithFields(log.Fields{
			"requested": *workerCount,
			"effective": clampedWorkerCount,
		}).Warn("sidecar worker count clamped")
	}

	log.WithField("workers", clampedWorkerCount).Info("Go sidecar starting")
	core.SendJSON(OutputEvent{Type: "log", Msg: fmt.Sprintf("=== GO SIDECAR STARTED - WORKERS: %d ===", clampedWorkerCount)})

	initHTTPClient()
	initScheduler()

	jobQueue := make(chan JobRequest, 100)
	var wg sync.WaitGroup
	shutdownChan := make(chan struct{})

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	for i := 0; i < clampedWorkerCount; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for job := range jobQueue {
				handleJob(job)
			}
		}()
	}

	go func() {
		<-sigChan
		close(shutdownChan)
	}()

	decoder := json.NewDecoder(os.Stdin)
	for {
		select {
		case <-shutdownChan:
			goto shutdown
		default:
			var job JobRequest
			if err := decoder.Decode(&job); err != nil {
				if err == io.EOF {
					close(shutdownChan)
					goto shutdown
				}
				core.SendJSON(OutputEvent{Type: "error", Msg: fmt.Sprintf("JSON decode error: %v", err)})
				continue
			}
			jobQueue <- job
		}
	}

shutdown:
	close(jobQueue)
	wg.Wait()
	core.SendJSON(OutputEvent{Type: "log", Msg: "=== GO SIDECAR SHUTDOWN COMPLETE ==="})
}

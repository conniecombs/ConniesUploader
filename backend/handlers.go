// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"image"
	_ "image/gif"
	"image/jpeg"
	_ "image/png"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/disintegration/imaging"

	"github.com/conniecombs/GolangVersion/core"
)

const (
	defaultThumbWidth = 100
	minThumbWidth     = 1
	maxThumbWidth     = 512
	// maxThumbnailPixels bounds decoded previews so a decompression bomb
	// cannot exhaust the sidecar's memory.
	maxThumbnailPixels = 50_000_000
)

// serviceUploadLimiter counts the uploads running on one service across all
// jobs. It stores no limit of its own: each job passes its configured Thread
// Limit to acquire, so no job can change the concurrency of another.
type serviceUploadLimiter struct {
	mu     sync.Mutex
	cond   *sync.Cond
	active int
}

var serviceUploadLimiters = struct {
	mu       sync.Mutex
	limiters map[string]*serviceUploadLimiter
}{
	limiters: make(map[string]*serviceUploadLimiter),
}

func newServiceUploadLimiter() *serviceUploadLimiter {
	limiter := &serviceUploadLimiter{}
	limiter.cond = sync.NewCond(&limiter.mu)
	return limiter
}

func getServiceUploadLimiter(service string) *serviceUploadLimiter {
	if service == "" {
		service = "__default__"
	}

	serviceUploadLimiters.mu.Lock()
	defer serviceUploadLimiters.mu.Unlock()
	limiter := serviceUploadLimiters.limiters[service]
	if limiter == nil {
		limiter = newServiceUploadLimiter()
		serviceUploadLimiters.limiters[service] = limiter
	}
	return limiter
}

// acquire waits until fewer than limit uploads run on the service, counting
// every job, then takes a slot. limit is the calling job's Thread Limit.
// Jobs with different limits never override each other: the service total
// stays within the largest limit among running jobs, and a job with a lower
// limit starts a file only while the total is below its own limit.
// It returns false, without taking a slot, if ctx ends first (the batch was
// cancelled while the file waited).
func (l *serviceUploadLimiter) acquire(ctx context.Context, limit int) bool {
	if limit < 1 {
		limit = 1
	}
	stop := context.AfterFunc(ctx, func() {
		l.mu.Lock()
		l.cond.Broadcast()
		l.mu.Unlock()
	})
	defer stop()
	l.mu.Lock()
	defer l.mu.Unlock()
	for l.active >= limit {
		if ctx.Err() != nil {
			return false
		}
		l.cond.Wait()
	}
	if ctx.Err() != nil {
		return false
	}
	l.active++
	return true
}

func (l *serviceUploadLimiter) release() {
	l.mu.Lock()
	if l.active > 0 {
		l.active--
	}
	l.cond.Broadcast()
	l.mu.Unlock()
}

func handleJob(job JobRequest) {
	if job.ReleaseQueueHold != nil {
		defer job.ReleaseQueueHold()
	}
	ensureInitialized()
	defer func() {
		if r := recover(); r != nil {
			sendJobEvent(&job, OutputEvent{Type: "error", Msg: fmt.Sprintf("Panic: %v", r)})
		}
	}()
	if err := core.ValidateJobRequest(&job); err != nil {
		sendJobEvent(&job, OutputEvent{Type: "error", Msg: fmt.Sprintf("Invalid job: %v", err)})
		return
	}
	if job.RateLimits != nil {
		updateRateLimiter(job.Service, job.RateLimits)
	}
	if job.RetryConfig == nil {
		job.RetryConfig = getDefaultRetryConfig()
	}

	switch job.Action {
	case "http_upload":
		handleHttpUpload(job)
	case "http_request":
		handleHttpRequest(job)
	case "http_batch_resolve":
		handleHttpBatchResolve(job)
	case "generate_thumb":
		handleGenerateThumb(job)
	case "cancel":
		handleCancel(job)
	case "session_open":
		handleSessionOpen(job)
	case "session_close":
		handleSessionClose(job)
	default:
		sendJobEvent(&job, OutputEvent{Type: "error", Msg: fmt.Sprintf("Unsupported action: %s", job.Action)})
	}
}

// ---------------------------------------------------------------------------
// Upload handlers
// ---------------------------------------------------------------------------

func handleHttpUpload(job JobRequest) {
	if job.RawResponse {
		processUploadFiles(job, processRawFileCtx)
		return
	}
	if job.HttpSpec == nil {
		sendJobEvent(&job, OutputEvent{Type: "error", Msg: "http_upload requires http_spec field"})
		return
	}
	processUploadFiles(job, processFileGenericCtx)
}

func handleCancel(job JobRequest) {
	// Mark the batch cancelled before closing its sessions: a session_open
	// racing with this cancel then either is closed here or sees the mark.
	live := core.CancelBatch(job.BatchID)
	closed := core.CloseBatchSessions(job.BatchID)
	sendJobEvent(&job, OutputEvent{
		Type: "log",
		Msg:  fmt.Sprintf("Batch cancelled: %s (live jobs: %t, sessions closed: %d)", job.BatchID, live, closed),
	})
}

// ---------------------------------------------------------------------------
// Transport sessions
// ---------------------------------------------------------------------------

// handleSessionOpen opens a session unless the deadline Python waits for
// (timeout_seconds, from when the job was queued) has passed: Python has
// then given up on the open and would never close the session.
func handleSessionOpen(job JobRequest) {
	ensureInitialized()
	if _, msg, expired := queueDeadline(&job, job.TimeoutSeconds); expired {
		sendJobEvent(&job, OutputEvent{Type: "result", Status: "failed", Msg: msg})
		return
	}
	session, err := core.OpenSession(client, job.BatchID)
	if err != nil {
		sendJobEvent(&job, OutputEvent{Type: "result", Status: "failed", Msg: err.Error()})
		return
	}
	sendJobEvent(&job, OutputEvent{
		Type:   "result",
		Status: "success",
		Data:   map[string]string{"session_id": session.ID},
	})
}

// handleSessionClose closes a session. Closing one that is not open is not an
// error (it may have been closed by a batch cancel or reaped). A reply goes
// only to a request with an id, so an uncorrelated result never reaches a
// listener that would take it for an upload result.
func handleSessionClose(job JobRequest) {
	closed := core.CloseSession(job.SessionID)
	if job.ID == "" {
		sendJobEvent(&job, OutputEvent{Type: "log", Msg: fmt.Sprintf("Session closed: %s (was open: %t)", job.SessionID, closed)})
		return
	}
	sendJobEvent(&job, OutputEvent{
		Type:   "result",
		Status: "success",
		Data:   map[string]string{"session_id": job.SessionID, "closed": strconv.FormatBool(closed)},
	})
}

func emitCancelledFiles(job *JobRequest, files []string) {
	for _, fp := range files {
		sendJobEvent(job, OutputEvent{Type: "status", FilePath: fp, Status: "Cancelled"})
		sendJobEvent(job, OutputEvent{Type: "error", FilePath: fp, Msg: "Upload cancelled"})
	}
}

func processUploadFiles(job JobRequest, processor func(context.Context, string, *JobRequest)) {
	batchCtx, releaseBatch := core.RegisterBatch(job.BatchID)
	defer releaseBatch()
	if batchCtx.Err() != nil {
		emitCancelledFiles(&job, job.Files)
		sendJobEvent(&job, OutputEvent{Type: "batch_complete", Status: "done"})
		return
	}

	// The configured Thread Limit bounds uploads on the service; the job's
	// file count only caps how many goroutines this job spawns.
	threadLimit := workerLimit(job.Config)
	if threadLimit < 1 {
		threadLimit = 1
	}
	maxWorkers := threadLimit
	if n := len(job.Files); n > 0 && maxWorkers > n {
		maxWorkers = n
	}
	// upload_order matches results by the order uploads finish, which is
	// only defined when the job's uploads do not overlap. A sequential job
	// asks for that order itself; one worker takes the files in list order.
	if job.Sequential || core.ResolveNeedsSequentialUploads(job.ResolveSpec) {
		maxWorkers = 1
	}

	// A job on a transport session uploads with the session's client. The
	// session stays in use (never reaped) until the job ends.
	if job.SessionID != "" {
		session, releaseSession, err := core.AcquireSession(job.SessionID)
		if err != nil {
			for _, fp := range job.Files {
				sendJobEvent(&job, OutputEvent{Type: "status", FilePath: fp, Status: "Failed"})
				sendJobEvent(&job, OutputEvent{Type: "error", FilePath: fp, Msg: err.Error()})
			}
			sendJobEvent(&job, OutputEvent{Type: "batch_complete", Status: "done"})
			return
		}
		defer releaseSession()
		job.Session = session
	}

	// Once-per-job session/login for hosts that declare pre_request (Vipr, Turbo, ImageBam).
	// Concurrent files then share cookies/tokens instead of re-authenticating per file.
	// A raw job never runs pre_request: Python logs in on its transport session.
	if !job.RawResponse && len(job.Files) > 1 && job.HttpSpec != nil && job.HttpSpec.PreRequest != nil && !job.HttpSpec.PreRequest.OncePerFile {
		sendJobEvent(&job, OutputEvent{
			Type: "log",
			Msg:  fmt.Sprintf("Preparing shared upload session for %d files (service %s)", len(job.Files), job.Service),
		})
		// Derived from the batch so Stop ends the login at once.
		sessionCtx, sessionCancel := context.WithTimeout(batchCtx, core.PreRequestTimeout*3)
		err := core.PrepareSharedUploadSession(sessionCtx, client, &job)
		sessionCancel()
		if err != nil && batchCtx.Err() != nil {
			emitCancelledFiles(&job, job.Files)
			sendJobEvent(&job, OutputEvent{Type: "batch_complete", Status: "done"})
			return
		}
		if err != nil {
			msg := fmt.Sprintf("session setup failed: %v", err)
			for _, fp := range job.Files {
				sendJobEvent(&job, OutputEvent{Type: "status", FilePath: fp, Status: "Failed"})
				sendJobEvent(&job, OutputEvent{Type: "error", FilePath: fp, Msg: msg})
			}
			sendJobEvent(&job, OutputEvent{Type: "batch_complete", Status: "done"})
			return
		}
		sendJobEvent(&job, OutputEvent{
			Type: "log",
			Msg:  fmt.Sprintf("Shared upload session ready (service %s); starting %d concurrent workers", job.Service, maxWorkers),
		})
	}

	filesChan := make(chan string, len(job.Files))
	limiter := getServiceUploadLimiter(job.Service)
	var wg sync.WaitGroup
	for i := 0; i < maxWorkers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for fp := range filesChan {
				if batchCtx.Err() != nil {
					emitCancelledFiles(&job, []string{fp})
					continue
				}
				if err := core.ValidateFilePath(fp); err != nil {
					sendJobEvent(&job, OutputEvent{Type: "status", FilePath: fp, Status: "Failed"})
					sendJobEvent(&job, OutputEvent{Type: "error", FilePath: fp, Msg: "Invalid file: " + err.Error()})
					continue
				}
				// Only surface "Waiting" when the service-wide slot is contested.
				// Otherwise go straight to Preparing so UI matches concurrent progress.
				if !limiter.acquire(batchCtx, threadLimit) {
					emitCancelledFiles(&job, []string{fp})
					continue
				}
				func() {
					defer limiter.release()
					sendJobEvent(&job, OutputEvent{
						Type:     "log",
						FilePath: fp,
						Msg: fmt.Sprintf(
							"Upload slot acquired: %s (service %s, concurrent limit %d)",
							filepath.Base(fp),
							job.Service,
							threadLimit,
						),
					})
					sendJobEvent(&job, OutputEvent{Type: "status", FilePath: fp, Status: "Preparing"})
					processor(batchCtx, fp, &job)
				}()
			}
		}()
	}
	for _, f := range job.Files {
		filesChan <- f
	}
	close(filesChan)
	wg.Wait()
	sendJobEvent(&job, OutputEvent{Type: "batch_complete", Status: "done"})
}

func processFileGeneric(fp string, job *JobRequest) {
	processFileGenericCtx(context.Background(), fp, job)
}

func processFileGenericCtx(parent context.Context, fp string, job *JobRequest) {
	// No wall-clock deadline: a large file on a slow uplink takes as long as
	// it needs. core bounds each attempt by a stall timeout and a bounded wait
	// for the host's answer, so ctx ends only when the batch is cancelled.
	ctx, cancel := context.WithCancel(parent)
	defer cancel()

	type result struct {
		url, thumb string
		data       map[string]string
		err        error
	}
	resultChan := make(chan result, 1)

	go func() {
		sendJobEvent(job, OutputEvent{Type: "status", FilePath: fp, Status: "Preparing"})
		uploadResult, err := executeHttpUploadWithData(ctx, fp, job)

		select {
		case resultChan <- result{uploadResult.URL, uploadResult.Thumb, uploadResult.Data, err}:
		case <-ctx.Done():
		}
	}()

	select {
	case res := <-resultChan:
		if res.err == nil && strings.TrimSpace(res.url) == "" {
			// A file is only Done when it has a link to show.
			res.err = fmt.Errorf("upload finished without an image link")
		}
		if res.err != nil {
			if parent.Err() == context.Canceled {
				emitCancelledFiles(job, []string{fp})
				return
			}
			sendJobEvent(job, OutputEvent{Type: "status", FilePath: fp, Status: "Failed"})
			sendJobEvent(job, OutputEvent{Type: "error", FilePath: fp, Msg: res.err.Error()})
		} else {
			event := OutputEvent{Type: "result", FilePath: fp, Url: res.url, Thumb: res.thumb}
			if len(res.data) > 0 {
				event.Data = res.data
			}
			sendJobEvent(job, event)
			sendJobEvent(job, OutputEvent{Type: "status", FilePath: fp, Status: "Done"})
		}
	case <-ctx.Done():
		emitCancelledFiles(job, []string{fp})
	}
}

// processRawFileCtx uploads one file of a raw job and reports the host's
// answer as a result event with response_body, status_code and final_url,
// then the non-terminal status "Uploaded". Python parses the answer and ends
// the file with Done or Failed. Transport failures end it here with Failed,
// a batch cancel with Cancelled.
func processRawFileCtx(parent context.Context, fp string, job *JobRequest) {
	ctx, cancel := context.WithCancel(parent)
	defer cancel()
	uploadClient := client
	if job.Session != nil {
		uploadClient = job.Session.Client
		stop := context.AfterFunc(job.Session.Context(), cancel)
		defer stop()
	}

	type rawResult struct {
		result core.RawUploadResult
		err    error
	}
	resultChan := make(chan rawResult, 1)
	go func() {
		result, err := core.ExecuteRawUpload(ctx, uploadClient, fp, job)
		resultChan <- rawResult{result, err}
	}()

	var res rawResult
	select {
	case res = <-resultChan:
	case <-ctx.Done():
		res.err = ctx.Err()
	}
	if res.err != nil {
		failed := OutputEvent{Type: "status", FilePath: fp, Status: "Failed"}
		if core.UploadBodySent(res.err) {
			// The host got the whole file and may have stored it.
			failed.Data = map[string]string{"body_sent": "true"}
		}
		// parent is the batch context, which has no deadline (an upload has
		// no wall-clock limit): it ends only when the batch is cancelled.
		switch {
		case errors.Is(parent.Err(), context.Canceled):
			emitCancelledFiles(job, []string{fp})
			return
		case job.Session != nil && job.Session.Closed():
			res.err = core.ErrSessionClosed
		}
		sendJobEvent(job, failed)
		sendJobEvent(job, OutputEvent{Type: "error", FilePath: fp, Msg: res.err.Error()})
		return
	}
	sendJobEvent(job, OutputEvent{
		Type:     "result",
		FilePath: fp,
		Data: map[string]string{
			"response_body": res.result.Body,
			"status_code":   strconv.Itoa(res.result.StatusCode),
			"final_url":     res.result.FinalURL,
		},
	})
	sendJobEvent(job, OutputEvent{Type: "status", FilePath: fp, Status: "Uploaded"})
}

// ---------------------------------------------------------------------------
// Generic HTTP request handler
// ---------------------------------------------------------------------------

func handleHttpRequest(job JobRequest) {
	ensureInitialized()

	spec := job.GenericSpec
	if spec == nil {
		sendJobEvent(&job, OutputEvent{Type: "result", Status: "failed", Msg: "http_request requires generic_spec field"})
		return
	}

	timeout, msg, expired := queueDeadline(&job, spec.TimeoutSeconds)
	if expired {
		sendJobEvent(&job, OutputEvent{Type: "result", Status: "failed", Msg: msg})
		return
	}

	// A request on a transport session uses the session's client and jar,
	// and is aborted when the session closes (including a batch cancel).
	requestClient := client
	baseCtx := context.Background()
	var session *core.TransportSession
	if spec.SessionID != "" {
		var release func()
		var err error
		session, release, err = core.AcquireSession(spec.SessionID)
		if err != nil {
			sendJobEvent(&job, OutputEvent{Type: "result", Status: "failed", Msg: err.Error()})
			return
		}
		defer release()
		requestClient = session.Client
		baseCtx = session.Context()
	}

	if spec.ResetCookies {
		core.ResetSiteCookies(requestClient, spec.URL)
	}
	ctx, cancel := context.WithTimeout(baseCtx, timeout)
	defer cancel()

	extracted, err := core.ExecuteGenericRequest(ctx, requestClient, spec, &job)
	if err != nil {
		msg := err.Error()
		if session != nil && session.Closed() {
			msg = core.ErrSessionClosed.Error()
		}
		sendJobEvent(&job, OutputEvent{Type: "result", Status: "failed", Msg: msg})
		return
	}

	// Remove internal fields before sending to Python.
	cleanData := make(map[string]string, len(extracted))
	for k, v := range extracted {
		if !strings.HasPrefix(k, "__") || !strings.HasSuffix(k, "__") {
			cleanData[k] = v
		}
	}
	if spec.IncludeTransportMetadata || spec.IncludeResponseBody {
		if statusCode := extracted["__status_code__"]; strings.TrimSpace(statusCode) != "" {
			cleanData["status_code"] = statusCode
		}
		if finalURL := extracted["__final_url__"]; strings.TrimSpace(finalURL) != "" {
			cleanData["final_url"] = finalURL
		}
	}
	if spec.IncludeResponseBody {
		cleanData["response_body"] = extracted["__response_body__"]
	}

	sendJobEvent(&job, OutputEvent{Type: "result", Status: "success", Data: cleanData})
}

// ---------------------------------------------------------------------------
// Batch resolve handler
// ---------------------------------------------------------------------------

func handleHttpBatchResolve(job JobRequest) {
	ensureInitialized()

	spec := job.ResolveSpec
	if spec == nil {
		sendJobEvent(&job, OutputEvent{Type: "result", Status: "failed", Msg: "http_batch_resolve requires resolve_spec field"})
		return
	}

	// Build file name map from config.
	fileNames := make(map[string]string, len(job.Files))
	for _, fp := range job.Files {
		key := "filename:" + fp
		if name, ok := job.Config[key]; ok {
			fileNames[fp] = name
		}
	}

	ctx, cancel := context.WithTimeout(context.Background(), core.ClientTimeout)
	defer cancel()

	results, err := core.ExecuteBatchResolve(ctx, client, spec, job.Files, fileNames)

	// Emit results per file.
	for _, fp := range job.Files {
		if pair, ok := results[fp]; ok {
			if strings.TrimSpace(pair[0]) == "" {
				sendJobEvent(&job, OutputEvent{Type: "status", FilePath: fp, Status: "Failed"})
				sendJobEvent(&job, OutputEvent{Type: "error", FilePath: fp, Msg: "batch resolver returned an empty image link"})
			} else {
				sendJobEvent(&job, OutputEvent{Type: "result", FilePath: fp, Url: pair[0], Thumb: pair[1]})
				sendJobEvent(&job, OutputEvent{Type: "status", FilePath: fp, Status: "Done"})
			}
		} else {
			sendJobEvent(&job, OutputEvent{Type: "status", FilePath: fp, Status: "Failed"})
			msg := "batch resolver did not find link for file"
			if err != nil {
				msg = err.Error()
			}
			sendJobEvent(&job, OutputEvent{Type: "error", FilePath: fp, Msg: msg})
		}
	}

	sendJobEvent(&job, OutputEvent{Type: "batch_complete", Status: "done"})
}

// ---------------------------------------------------------------------------
// Thumbnail generation
// ---------------------------------------------------------------------------

func handleGenerateThumb(job JobRequest) {
	if len(job.Files) == 0 {
		sendJobEvent(&job, OutputEvent{Type: "error", Msg: "No file provided"})
		return
	}
	w, err := strconv.Atoi(job.Config["width"])
	if err != nil || w <= 0 {
		w = defaultThumbWidth
	}
	if w < minThumbWidth {
		w = minThumbWidth
	}
	if w > maxThumbWidth {
		w = maxThumbWidth
	}

	fp := job.Files[0]
	f, err := os.Open(fp) // #nosec G304 -- path is validated before this action is issued.
	if err != nil {
		sendJobEvent(&job, OutputEvent{Type: "error", Msg: "File not found"})
		return
	}
	defer f.Close()

	header, _, err := image.DecodeConfig(f)
	if err != nil {
		sendJobEvent(&job, OutputEvent{Type: "error", Msg: "Decode failed"})
		return
	}
	if header.Width <= 0 || header.Height <= 0 || int64(header.Width)*int64(header.Height) > maxThumbnailPixels {
		sendJobEvent(&job, OutputEvent{Type: "error", Msg: "Image too large to preview"})
		return
	}
	if _, err := f.Seek(0, io.SeekStart); err != nil {
		sendJobEvent(&job, OutputEvent{Type: "error", Msg: "Decode failed"})
		return
	}

	img, _, err := image.Decode(f)
	if err != nil {
		sendJobEvent(&job, OutputEvent{Type: "error", Msg: "Decode failed"})
		return
	}
	thumb := imaging.Resize(img, w, 0, imaging.Lanczos)
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, thumb, &jpeg.Options{Quality: 70}); err != nil {
		sendJobEvent(&job, OutputEvent{Type: "error", Msg: "Encode failed"})
		return
	}
	sendJobEvent(&job, OutputEvent{
		Type:     "data",
		Data:     base64.StdEncoding.EncodeToString(buf.Bytes()),
		Status:   "success",
		FilePath: fp,
	})
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// queueDeadline applies the deadline Python asked for (seconds, clamped to
// the client ceiling) from when the job was queued, not from when a worker
// picked it up; otherwise a job that waited behind others could run after
// Python already gave up on it. It returns the time left, or, once the
// deadline has passed, the failure message and expired true.
func queueDeadline(job *JobRequest, seconds int) (remaining time.Duration, msg string, expired bool) {
	timeout := core.RequestTimeout(seconds)
	if job.EnqueuedAt.IsZero() {
		return timeout, "", false
	}
	waited := time.Since(job.EnqueuedAt)
	if waited >= timeout {
		return 0, fmt.Sprintf("request deadline passed while queued (waited %.0fs)", waited.Seconds()), true
	}
	return timeout - waited, "", false
}

func workerLimit(config map[string]string) int {
	if w, err := strconv.Atoi(config["threads"]); err == nil && w > 0 {
		return w
	}
	return 2
}

func sendJobEvent(job *JobRequest, event OutputEvent) {
	if event.ID == "" && job != nil {
		event.ID = job.ID
	}
	sendJSON(event)
}

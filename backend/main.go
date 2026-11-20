// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
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
	client = &http.Client{
		Timeout: core.ClientTimeout,
		Jar:     core.NewSwappableJar(),
		Transport: &http.Transport{
			MaxIdleConns:          200,
			MaxIdleConnsPerHost:   50,
			MaxConnsPerHost:       50,
			IdleConnTimeout:       90 * time.Second,
			ResponseHeaderTimeout: core.ResponseHeaderTimeout,
			ForceAttemptHTTP2:     true,
		},
	}
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
	workerCount := flag.Int("workers", 8, "Number of upload worker goroutines")
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

	shutdownChan := make(chan struct{})
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-sigChan
		close(shutdownChan)
	}()

	runSidecar(os.Stdin, clampedWorkerCount, shutdownChan)
	core.SendJSON(OutputEvent{Type: "log", Msg: "=== GO SIDECAR SHUTDOWN COMPLETE ==="})
}

// requestWorkerCount sizes the pool for every action except http_upload and
// the session requests below (http_request, http_batch_resolve,
// generate_thumb). It is separate from the upload pool so a login, a forum
// post or a gallery call never waits behind queued uploads.
const requestWorkerCount = 4

// sessionRequestWorkerCount sizes the pool for the Python upload path's
// requests: session_open, session_close and every http_request on a
// transport session (a host's login, a parser's follow-ups and result-page
// polls). Their deadlines count from when they were queued, so on the
// shared pool a parser's follow-up queued behind slow forum posts or gallery
// calls expired and turned an upload the host had stored into a failure.
// Python has at most POST_PROCESS_WORKERS (4) parsers and one dispatch
// thread (a session open or login) waiting on a session request at a time,
// so with this many workers none of them waits for a worker.
// frontend/tests/test_build_contract.py checks the two numbers agree.
const sessionRequestWorkerCount = 8

// isSessionRequest reports whether job belongs on the session request pool.
func isSessionRequest(job *JobRequest) bool {
	switch job.Action {
	case "session_open", "session_close":
		return true
	case "http_request":
		return job.GenericSpec != nil && job.GenericSpec.SessionID != ""
	}
	return false
}

// jobQueue is an unbounded FIFO. Pushing never blocks, so the stdin reader
// keeps reading (and handling cancel) however many upload jobs are waiting.
type jobQueue struct {
	mu     sync.Mutex
	cond   *sync.Cond
	jobs   []JobRequest
	closed bool
}

func newJobQueue() *jobQueue {
	q := &jobQueue{}
	q.cond = sync.NewCond(&q.mu)
	return q
}

func (q *jobQueue) push(job JobRequest) {
	q.mu.Lock()
	q.jobs = append(q.jobs, job)
	q.mu.Unlock()
	q.cond.Signal()
}

// pop waits for the next job; ok is false once the queue is closed and empty.
func (q *jobQueue) pop() (job JobRequest, ok bool) {
	q.mu.Lock()
	defer q.mu.Unlock()
	for len(q.jobs) == 0 && !q.closed {
		q.cond.Wait()
	}
	if len(q.jobs) == 0 {
		return JobRequest{}, false
	}
	job = q.jobs[0]
	q.jobs[0] = JobRequest{}
	q.jobs = q.jobs[1:]
	return job, true
}

func (q *jobQueue) close() {
	q.mu.Lock()
	q.closed = true
	q.mu.Unlock()
	q.cond.Broadcast()
}

func startWorkers(wg *sync.WaitGroup, queue *jobQueue, count int) {
	for i := 0; i < count; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for {
				job, ok := queue.pop()
				if !ok {
					return
				}
				handleJob(job)
			}
		}()
	}
}

// runSidecar reads one JSON job per line from input until input ends or
// shutdown is closed, then waits for every queued job to finish. Uploads run
// on uploadWorkers workers, session requests on their own pool, every other
// action on a third pool; cancel is handled inline.
func runSidecar(input io.Reader, uploadWorkers int, shutdown <-chan struct{}) {
	core.StartSessionReaper()
	uploads := newJobQueue()
	requests := newJobQueue()
	sessionRequests := newJobQueue()
	var wg sync.WaitGroup
	startWorkers(&wg, uploads, uploadWorkers)
	startWorkers(&wg, requests, requestWorkerCount)
	startWorkers(&wg, sessionRequests, sessionRequestWorkerCount)
	defer func() {
		uploads.close()
		requests.close()
		sessionRequests.close()
		wg.Wait()
	}()

	// Requests are JSON lines. Each line is decoded on its own, so a malformed
	// line is reported once and the next line is still read (a json.Decoder's
	// error is sticky and would repeat forever).
	reader := bufio.NewReader(input)
	for {
		select {
		case <-shutdown:
			return
		default:
		}
		line, readErr := reader.ReadBytes('\n')
		if len(bytes.TrimSpace(line)) == 0 {
			if readErr != nil {
				return
			}
			continue
		}
		var job JobRequest
		if err := json.Unmarshal(line, &job); err != nil {
			core.SendJSON(OutputEvent{Type: "error", Msg: fmt.Sprintf("JSON decode error: %v", err)})
			if readErr != nil {
				return
			}
			continue
		}
		job.EnqueuedAt = time.Now()
		switch job.Action {
		case "cancel":
			// Handled inline so a cancel is never stuck behind busy workers.
			handleJob(job)
		case "http_upload":
			// The job's session stays in use while the job waits for an
			// upload worker, so it is never reaped from under a queued job.
			if job.SessionID != "" {
				job.ReleaseQueueHold = core.HoldSession(job.SessionID)
			}
			uploads.push(job)
		default:
			if isSessionRequest(&job) {
				sessionRequests.push(job)
			} else {
				requests.push(job)
			}
		}
	}
}

// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"fmt"
	"image"
	_ "image/gif"
	"image/jpeg"
	_ "image/png"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"

	"github.com/disintegration/imaging"

	"github.com/conniecombs/GolangVersion/core"
)

const (
	defaultThumbWidth = 100
	minThumbWidth     = 1
	maxThumbWidth     = 512
)

type serviceUploadLimiter struct {
	mu     sync.Mutex
	cond   *sync.Cond
	active int
	limit  int
}

var serviceUploadLimiters = struct {
	mu       sync.Mutex
	limiters map[string]*serviceUploadLimiter
}{
	limiters: make(map[string]*serviceUploadLimiter),
}

func newServiceUploadLimiter(limit int) *serviceUploadLimiter {
	limiter := &serviceUploadLimiter{limit: limit}
	limiter.cond = sync.NewCond(&limiter.mu)
	return limiter
}

func getServiceUploadLimiter(service string, limit int) *serviceUploadLimiter {
	if service == "" {
		service = "__default__"
	}
	if limit < 1 {
		limit = 1
	}

	serviceUploadLimiters.mu.Lock()
	limiter := serviceUploadLimiters.limiters[service]
	if limiter == nil {
		limiter = newServiceUploadLimiter(limit)
		serviceUploadLimiters.limiters[service] = limiter
	}
	serviceUploadLimiters.mu.Unlock()

	limiter.setLimit(limit)
	return limiter
}

func (l *serviceUploadLimiter) setLimit(limit int) {
	l.mu.Lock()
	if l.limit != limit {
		l.limit = limit
		l.cond.Broadcast()
	}
	l.mu.Unlock()
}

func (l *serviceUploadLimiter) acquire() {
	l.mu.Lock()
	defer l.mu.Unlock()
	for l.active >= l.limit {
		l.cond.Wait()
	}
	l.active++
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
	default:
		sendJobEvent(&job, OutputEvent{Type: "error", Msg: fmt.Sprintf("Unsupported action: %s", job.Action)})
	}
}

// ---------------------------------------------------------------------------
// Upload handlers
// ---------------------------------------------------------------------------

func handleHttpUpload(job JobRequest) {
	if job.HttpSpec == nil {
		sendJobEvent(&job, OutputEvent{Type: "error", Msg: "http_upload requires http_spec field"})
		return
	}
	processUploadFiles(job, processFileGeneric)
}

func processUploadFiles(job JobRequest, processor func(string, *JobRequest)) {
	filesChan := make(chan string, len(job.Files))
	maxWorkers := workerLimit(job.Config)
	limiter := getServiceUploadLimiter(job.Service, maxWorkers)
	var wg sync.WaitGroup
	for i := 0; i < maxWorkers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for fp := range filesChan {
				sendJobEvent(&job, OutputEvent{Type: "status", FilePath: fp, Status: "Waiting"})
				limiter.acquire()
				func() {
					defer limiter.release()
					sendJobEvent(&job, OutputEvent{
						Type:     "log",
						FilePath: fp,
						Msg: fmt.Sprintf(
							"Upload slot acquired: %s (service %s, limit %d)",
							filepath.Base(fp),
							job.Service,
							maxWorkers,
						),
					})
					sendJobEvent(&job, OutputEvent{Type: "status", FilePath: fp, Status: "Preparing"})
					processor(fp, &job)
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
	ctx, cancel := context.WithTimeout(context.Background(), core.ClientTimeout)
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
		if res.err != nil {
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
		sendJobEvent(job, OutputEvent{Type: "status", FilePath: fp, Status: "Timeout"})
		sendJobEvent(job, OutputEvent{Type: "error", FilePath: fp, Msg: "Upload timed out"})
	}
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

	ctx, cancel := context.WithTimeout(context.Background(), core.ClientTimeout)
	defer cancel()

	extracted, err := core.ExecuteGenericRequest(ctx, client, spec, &job)
	if err != nil {
		sendJobEvent(&job, OutputEvent{Type: "result", Status: "failed", Msg: err.Error()})
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

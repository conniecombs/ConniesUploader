// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"context"
	"fmt"
	"path/filepath"
	"strconv"
	"sync"

	log "github.com/sirupsen/logrus"

	"github.com/conniecombs/GolangVersion/core"
	"github.com/conniecombs/GolangVersion/services"
)

const (
	defaultUploadWorkers = 2
	minUploadWorkers     = 1
	maxUploadWorkers     = 16
)

type fileProcessor func(string, *JobRequest)
type uploadOperation func(context.Context, string, *JobRequest) (string, string, error)

func handleUpload(job JobRequest) {
	processFiles(job, processFile)
}

func handleHttpUpload(job JobRequest) {
	if job.HttpSpec == nil {
		sendJSON(OutputEvent{Type: "error", Msg: "http_upload requires http_spec field"})
		return
	}
	processFiles(job, processFileGeneric)
}

func processFiles(job JobRequest, processor fileProcessor) {
	filesChan := make(chan string, len(job.Files))
	var wg sync.WaitGroup

	for i := 0; i < workerLimit(job.Config); i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for fp := range filesChan {
				processor(fp, &job)
			}
		}()
	}
	for _, f := range job.Files {
		filesChan <- f
	}
	close(filesChan)
	wg.Wait()
	sendJSON(OutputEvent{Type: "batch_complete", Status: "done"})
}

func processFile(fp string, job *JobRequest) {
	ensureInitialized()
	processUploadFile(fp, job, uploadWithService)
}

func processFileGeneric(fp string, job *JobRequest) {
	ensureInitialized()
	processUploadFile(fp, job, func(ctx context.Context, fp string, job *JobRequest) (string, string, error) {
		return executeHttpUpload(ctx, fp, job)
	})
}

func processUploadFile(fp string, job *JobRequest, upload uploadOperation) {
	ctx, cancel := context.WithTimeout(context.Background(), core.ClientTimeout)
	defer cancel()

	type result struct {
		url   string
		thumb string
		err   error
	}
	resultChan := make(chan result, 1)

	go func() {
		sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Uploading"})

		cfg := job.RetryConfig
		if cfg == nil {
			cfg = getDefaultRetryConfig()
		}

		type uploadResult struct {
			url   string
			thumb string
		}
		res, err := retryWithBackoff(ctx, cfg, func() (uploadResult, int, error) {
			imgURL, thumb, err := upload(ctx, fp, job)
			return uploadResult{url: imgURL, thumb: thumb}, extractStatusCode(err), err
		}, log.WithField("file", filepath.Base(fp)))

		select {
		case resultChan <- result{url: res.url, thumb: res.thumb, err: err}:
		case <-ctx.Done():
		}
	}()

	select {
	case res := <-resultChan:
		if res.err != nil {
			sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Failed"})
			sendJSON(OutputEvent{Type: "error", FilePath: fp, Msg: res.err.Error()})
			return
		}
		sendJSON(OutputEvent{Type: "result", FilePath: fp, Url: res.url, Thumb: res.thumb})
		sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Done"})
	case <-ctx.Done():
		sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Timeout"})
		sendJSON(OutputEvent{Type: "error", FilePath: fp, Msg: "Upload timed out"})
	}
}

func uploadWithService(ctx context.Context, fp string, job *JobRequest) (string, string, error) {
	svc, ok := registry.Get(job.Service)
	if !ok {
		return "", "", fmt.Errorf("unknown service: %s", job.Service)
	}
	uploader, ok := svc.(services.Uploader)
	if !ok {
		return "", "", fmt.Errorf("service %s does not support upload", job.Service)
	}
	return uploader.Upload(ctx, fp, job)
}

func workerLimit(config map[string]string) int {
	workers := defaultUploadWorkers
	if w, err := strconv.Atoi(config["threads"]); err == nil && w > 0 {
		workers = w
	}
	if workers < minUploadWorkers {
		return minUploadWorkers
	}
	if workers > maxUploadWorkers {
		return maxUploadWorkers
	}
	return workers
}

// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package main

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"

	"github.com/conniecombs/GolangVersion/core"
)

func uploadJobForServer(t *testing.T, serverURL, batchID string) JobRequest {
	t.Helper()
	path := filepath.Join(t.TempDir(), "img.jpg")
	if err := os.WriteFile(path, []byte("jpeg-bytes"), 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}
	return JobRequest{
		ID:      "job-" + batchID,
		BatchID: batchID,
		Action:  "http_upload",
		Service: "example.host",
		Files:   []string{path},
		Config:  map[string]string{"threads": "1"},
		HttpSpec: &HttpRequestSpec{
			URL:    serverURL + "/upload",
			Method: http.MethodPost,
			MultipartFields: map[string]MultipartField{
				"image": {Type: "file", Value: ""},
			},
			ResponseParser: ResponseParserSpec{
				Type: "json", URLPath: "data.image_url", ThumbPath: "data.thumbnail_url",
			},
		},
		RetryConfig: &RetryConfig{MaxRetries: 0},
	}
}

func TestCancelActionAbortsInFlightUpload(t *testing.T) {
	received := make(chan struct{})
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(received)
		<-release
		_, _ = w.Write([]byte(`{"data":{"image_url":"u","thumbnail_url":"t"}}`))
	}))
	defer server.Close()
	defer close(release)

	oldClient := client
	client = server.Client()
	defer func() { client = oldClient }()

	job := uploadJobForServer(t, server.URL, "b-live")

	events := captureSidecarEvents(t, func() {
		done := make(chan struct{})
		go func() {
			defer close(done)
			handleJob(job)
		}()
		select {
		case <-received:
		case <-time.After(5 * time.Second):
			t.Error("server never received the upload request")
			return
		}
		handleJob(JobRequest{Action: "cancel", BatchID: "b-live"})
		select {
		case <-done:
		case <-time.After(5 * time.Second):
			t.Error("upload job did not finish after cancel")
		}
	})

	var cancelled bool
	for _, event := range events {
		if event.Type == "status" && event.Status == "Cancelled" && event.FilePath == job.Files[0] {
			cancelled = true
		}
	}
	if !cancelled {
		t.Fatalf("no Cancelled status for the in-flight file; events=%+v", events)
	}
	if got := len(eventsOfType(events, "batch_complete")); got != 1 {
		t.Fatalf("batch_complete count = %d, want 1", got)
	}
}

func TestQueuedJobForCancelledBatchIsSkipped(t *testing.T) {
	var hits int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&hits, 1)
		_, _ = w.Write([]byte(`{"data":{"image_url":"u","thumbnail_url":"t"}}`))
	}))
	defer server.Close()

	oldClient := client
	client = server.Client()
	defer func() { client = oldClient }()

	job := uploadJobForServer(t, server.URL, "b-queued")
	events := captureSidecarEvents(t, func() {
		handleJob(JobRequest{Action: "cancel", BatchID: "b-queued"})
		handleJob(job)
	})

	if atomic.LoadInt32(&hits) != 0 {
		t.Fatalf("server was contacted %d times for a cancelled batch", hits)
	}
	var cancelled int
	for _, event := range events {
		if event.Type == "status" && event.Status == "Cancelled" {
			cancelled++
		}
	}
	if cancelled != 1 {
		t.Fatalf("Cancelled statuses = %d, want 1; events=%+v", cancelled, events)
	}
	if got := len(eventsOfType(events, "batch_complete")); got != 1 {
		t.Fatalf("batch_complete count = %d, want 1", got)
	}
}

func TestValidateJobRequestAcceptsCancel(t *testing.T) {
	if err := core.ValidateJobRequest(&JobRequest{Action: "cancel", BatchID: "x"}); err != nil {
		t.Fatalf("cancel with batch id rejected: %v", err)
	}
	if err := core.ValidateJobRequest(&JobRequest{Action: "cancel"}); err == nil {
		t.Fatalf("cancel without batch id must be rejected")
	}
}

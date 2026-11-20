// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package main

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/conniecombs/GolangVersion/core"
)

// cancelTestSeq numbers the batch ids of the cancel tests. Cancelled ids are
// global state that outlives a test, so a fixed id would make the next run of
// the same test (go test -count=N) start with its batch already cancelled.
var cancelTestSeq atomic.Int64

func uniqueBatchID(prefix string) string {
	return fmt.Sprintf("%s-%d", prefix, cancelTestSeq.Add(1))
}

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

	batchID := uniqueBatchID("b-live")
	job := uploadJobForServer(t, server.URL, batchID)

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
		handleJob(JobRequest{Action: "cancel", BatchID: batchID})
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

	batchID := uniqueBatchID("b-queued")
	job := uploadJobForServer(t, server.URL, batchID)
	events := captureSidecarEvents(t, func() {
		handleJob(JobRequest{Action: "cancel", BatchID: batchID})
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

// Stop during a multi-file job's shared login must end the login at once and
// report every file Cancelled, not wait for the login's own time limit.
func TestCancelEndsSharedLoginPromptly(t *testing.T) {
	loginStarted := make(chan struct{})
	release := make(chan struct{})
	var loginOnce sync.Once
	var uploads int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/login":
			loginOnce.Do(func() { close(loginStarted) })
			select {
			case <-release:
			case <-r.Context().Done():
				return
			}
			_, _ = w.Write([]byte(`<input name="tok" value="abcd1234">`))
		default:
			atomic.AddInt32(&uploads, 1)
			_, _ = w.Write([]byte(`{"data":{"image_url":"u","thumbnail_url":"t"}}`))
		}
	}))
	defer server.Close()

	oldClient := client
	client = server.Client()
	defer func() { client = oldClient }()

	batchID := uniqueBatchID("b-login")
	job := uploadJobForServer(t, server.URL, batchID)
	second := filepath.Join(t.TempDir(), "img2.jpg")
	if err := os.WriteFile(second, []byte("jpeg-bytes-2"), 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}
	job.Files = append(job.Files, second)
	job.HttpSpec.PreRequest = &PreRequestSpec{
		URL:           server.URL + "/login",
		Method:        http.MethodGet,
		ResponseType:  "html",
		ExtractFields: map[string]string{"tok": "input[name='tok']"},
	}

	events := captureSidecarEvents(t, func() {
		done := make(chan struct{})
		go func() {
			defer close(done)
			handleJob(job)
		}()
		defer func() {
			close(release)
			<-done
		}()
		select {
		case <-loginStarted:
		case <-time.After(5 * time.Second):
			t.Error("server never received the login request")
			return
		}
		handleJob(JobRequest{Action: "cancel", BatchID: batchID})
		select {
		case <-done:
		case <-time.After(5 * time.Second):
			t.Error("job did not finish within 5s of cancel; it waited for the login")
		}
	})

	if got := atomic.LoadInt32(&uploads); got != 0 {
		t.Errorf("%d upload(s) sent after cancel", got)
	}
	statuses := map[string]string{}
	for _, event := range eventsOfType(events, "status") {
		if event.Status == "Cancelled" || event.Status == "Failed" || event.Status == "Done" {
			statuses[event.FilePath] = event.Status
		}
	}
	for _, fp := range job.Files {
		if statuses[fp] != "Cancelled" {
			t.Errorf("%s ended %q, want Cancelled; events=%+v", fp, statuses[fp], events)
		}
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

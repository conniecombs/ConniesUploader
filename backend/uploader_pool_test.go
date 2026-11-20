// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/conniecombs/GolangVersion/core"
)

// assertRequestRunsBehindUploads fills every upload worker, queues `queued`
// more upload jobs, then sends a generic request with a 3 s deadline and
// requires it to reach its host promptly.
func assertRequestRunsBehindUploads(t *testing.T, workers, queued int) {
	t.Helper()
	uploadStarted := make(chan struct{}, workers+queued)
	releaseUploads := make(chan struct{})
	uploads := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		uploadStarted <- struct{}{}
		select {
		case <-releaseUploads:
		case <-r.Context().Done():
		}
		_, _ = w.Write([]byte(`{"data":{"image_url":"u","thumbnail_url":"t"}}`))
	}))
	defer uploads.Close()

	requestSeen := make(chan struct{}, 1)
	forum := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestSeen <- struct{}{}
		_, _ = w.Write([]byte("ok"))
	}))
	defer forum.Close()

	oldClient := client
	client = &http.Client{Jar: core.NewSwappableJar()}
	defer func() { client = oldClient }()

	upload := uploadJobForServer(t, uploads.URL, "pool")
	upload.ID = "upload"
	upload.Service = "pool.test"
	upload.Config = map[string]string{"threads": "64"}
	uploadLine, _ := json.Marshal(upload)
	request := JobRequest{ID: "req", Action: "http_request", Service: "forum.test",
		GenericSpec: &core.GenericHttpRequestSpec{URL: forum.URL + "/login", TimeoutSeconds: 3}}
	requestLine, _ := json.Marshal(request)

	input, feed := io.Pipe()
	captureSidecarEvents(t, func() {
		done := make(chan struct{})
		go func() {
			defer close(done)
			runSidecar(input, workers, make(chan struct{}))
		}()
		defer func() {
			close(releaseUploads)
			_ = feed.Close()
			select {
			case <-done:
			case <-time.After(10 * time.Second):
				t.Error("sidecar did not shut down")
			}
		}()

		// The sidecar reads stdin as fast as it can; a write that cannot be
		// delivered means the reader is blocked, which the test must report
		// rather than hang on.
		sent := make(chan struct{})
		go func() {
			defer close(sent)
			for i := 0; i < workers+queued; i++ {
				if _, err := feed.Write(append(uploadLine, '\n')); err != nil {
					return
				}
			}
			_, _ = feed.Write(append(requestLine, '\n'))
		}()

		for i := 0; i < workers; i++ {
			select {
			case <-uploadStarted:
			case <-time.After(5 * time.Second):
				t.Error("upload workers never got busy")
				return
			}
		}
		select {
		case <-requestSeen:
		case <-time.After(3 * time.Second):
			t.Errorf("generic request did not run while %d upload workers were busy and %d jobs queued", workers, queued)
		}
		// Unblock a writer stuck on a blocked reader before shutting down.
		go func() { _, _ = io.Copy(io.Discard, input) }()
		<-sent
	})
}

// A generic request (forum login, gallery call) must run promptly while every
// upload worker is busy and more upload jobs are queued behind them.
func TestGenericRequestIsNotQueuedBehindUploads(t *testing.T) {
	assertRequestRunsBehindUploads(t, 2, 3)
}

// Reading stdin must not stop when many upload jobs are waiting for workers,
// or a request (and a cancel) sent after them would never be read.
func TestManyQueuedUploadsDoNotBlockReadingRequests(t *testing.T) {
	assertRequestRunsBehindUploads(t, 1, 150)
}

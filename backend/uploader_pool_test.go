// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
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

// The Python upload path's requests (session_open, session_close and every
// http_request on a transport session: logins, parser follow-ups, result-page
// polls) run on a pool of their own. With every shared request worker busy
// (slow forum posts, gallery calls) and more requests queued, as many session
// requests as Python can have in flight still run at once, and none of them
// expires in the queue.
func TestSessionRequestsDoNotWaitBehindOtherRequests(t *testing.T) {
	useSharedClient(t)
	release := make(chan struct{})
	slowStarted := make(chan struct{}, 64)
	host := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/slow") {
			slowStarted <- struct{}{}
			select {
			case <-release:
			case <-r.Context().Done():
			}
		}
		_, _ = w.Write([]byte("ok"))
	}))
	defer host.Close()
	batchID := uniqueBatchID("pool-sessions")
	request := func(id, path, sessionID string, timeout int) []byte {
		line, _ := json.Marshal(JobRequest{ID: id, Action: "http_request", Service: "pool.test",
			GenericSpec: &core.GenericHttpRequestSpec{URL: host.URL + path, TimeoutSeconds: timeout,
				SessionID: sessionID}})
		return append(line, '\n')
	}
	line := func(job JobRequest) []byte {
		encoded, _ := json.Marshal(job)
		return append(encoded, '\n')
	}

	input, feed := io.Pipe()
	streamSidecarEvents(t, func(events <-chan OutputEvent) {
		done := make(chan struct{})
		go func() {
			defer close(done)
			runSidecar(input, 1, make(chan struct{}))
		}()
		defer func() {
			close(release)
			_ = feed.Close()
			select {
			case <-done:
			case <-time.After(10 * time.Second):
				t.Error("sidecar did not shut down")
			}
		}()
		answers := map[string]OutputEvent{}
		await := func(ids ...string) {
			t.Helper()
			deadline := time.After(3 * time.Second)
			for _, id := range ids {
				for {
					if _, ok := answers[id]; ok {
						break
					}
					select {
					case event := <-events:
						if event.ID != "" && event.Type == "result" {
							answers[event.ID] = event
						}
					case <-deadline:
						t.Fatalf("no answer for %s while the shared request pool was busy", id)
					}
				}
			}
		}

		_, _ = feed.Write(line(JobRequest{ID: "open-1", Action: "session_open", BatchID: batchID, TimeoutSeconds: 2}))
		await("open-1")
		session := dataString(answers["open-1"], "session_id")

		// Every shared request worker is busy and more requests wait.
		for i := 0; i < 2*requestWorkerCount; i++ {
			_, _ = feed.Write(request(fmt.Sprintf("other-%d", i), "/slow/other", "", 30))
		}
		for i := 0; i < requestWorkerCount; i++ {
			select {
			case <-slowStarted:
			case <-time.After(5 * time.Second):
				t.Fatal("the shared request workers never got busy")
			}
		}

		// Python's four parsers poll a slow page on the session...
		for i := 0; i < 4; i++ {
			_, _ = feed.Write(request(fmt.Sprintf("poll-%d", i), "/slow/poll", session, 30))
		}
		for i := 0; i < 4; i++ {
			select {
			case <-slowStarted:
			case <-time.After(3 * time.Second):
				t.Fatal("the parsers' polls waited behind other requests")
			}
		}
		// ...while one more follow-up, the next group's open and a close run.
		_, _ = feed.Write(request("follow-up", "/fast", session, 1))
		_, _ = feed.Write(line(JobRequest{ID: "open-2", Action: "session_open", BatchID: batchID, TimeoutSeconds: 1}))
		await("follow-up", "open-2")
		if answers["follow-up"].Status != "success" || answers["open-2"].Status != "success" {
			t.Fatalf("follow-up = %+v, open = %+v", answers["follow-up"], answers["open-2"])
		}
		_, _ = feed.Write(line(JobRequest{ID: "close-2", Action: "session_close",
			SessionID: dataString(answers["open-2"], "session_id")}))
		await("close-2")
		if dataString(answers["close-2"], "closed") != "true" {
			t.Fatalf("close = %+v", answers["close-2"])
		}
	})
}

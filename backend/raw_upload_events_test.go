// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package main

import (
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/conniecombs/GolangVersion/core"
)

// asRawJob turns an upload job into a raw one: each file gets its own
// resolved request for url, and no http_spec.
func asRawJob(job JobRequest, url string) JobRequest {
	job.HttpSpec = nil
	job.RawResponse = true
	job.FileRequests = make(map[string]*core.RawUploadRequest, len(job.Files))
	for _, fp := range job.Files {
		job.FileRequests[fp] = &core.RawUploadRequest{
			URL:             url,
			Method:          http.MethodPost,
			MultipartFields: map[string]MultipartField{"image": {Type: "file", Value: fp}},
		}
	}
	return job
}

func writeNamedFiles(t *testing.T, names ...string) []string {
	t.Helper()
	dir := t.TempDir()
	paths := make([]string, len(names))
	for i, name := range names {
		paths[i] = filepath.Join(dir, name)
		if err := os.WriteFile(paths[i], []byte("bytes of "+name), 0o600); err != nil {
			t.Fatalf("write: %v", err)
		}
	}
	return paths
}

func eventsForFile(events []OutputEvent, fp string) []OutputEvent {
	var matched []OutputEvent
	for _, event := range events {
		if event.FilePath == fp && event.Type != "log" && event.Type != "progress" {
			matched = append(matched, event)
		}
	}
	return matched
}

func TestRawUploadJobEmitsTheRawResultThenUploaded(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		w.WriteHeader(http.StatusAccepted)
		_, _ = w.Write([]byte(`{"show_url":"https://img.example/v"}`))
	}))
	defer server.Close()
	useSharedClient(t)

	files := writeNamedFiles(t, "a.jpg", "b.jpg")
	job := asRawJob(JobRequest{ID: "raw-events", Action: "http_upload", Service: "raw-events.test", Files: files,
		Config: map[string]string{"threads": "2"}}, server.URL+"/upload")
	delete(job.FileRequests, files[1])

	events := captureSidecarEvents(t, func() { handleJob(job) })

	var sequence []string
	for _, event := range eventsForFile(events, files[0]) {
		if event.Type == "status" {
			sequence = append(sequence, "status:"+event.Status)
			continue
		}
		sequence = append(sequence, event.Type)
		if event.Type == "result" {
			if event.Url != "" || event.Thumb != "" {
				t.Fatalf("raw result carries url/thumb: %+v", event)
			}
			if dataString(event, "response_body") != `{"show_url":"https://img.example/v"}` ||
				dataString(event, "status_code") != "202" ||
				dataString(event, "final_url") != server.URL+"/upload" {
				t.Fatalf("raw result data = %+v", event.Data)
			}
		}
	}
	if len(sequence) < 2 {
		t.Fatalf("file events = %v, want a raw result and Uploaded (all events %+v)", sequence, events)
	}
	tail := sequence[len(sequence)-2:]
	if tail[0] != "result" || tail[1] != "status:Uploaded" {
		t.Fatalf("file events end %v, want [result status:Uploaded] (all %v)", tail, sequence)
	}
	for _, step := range sequence {
		if step == "status:Done" {
			t.Fatalf("a raw upload must never be Done from Go: %v", sequence)
		}
	}

	missing := eventsForFile(events, files[1])
	if len(missing) < 2 || missing[len(missing)-2].Status != "Failed" || missing[len(missing)-1].Msg != "missing upload request" {
		t.Fatalf("file without a request: %+v", missing)
	}
	if last := events[len(events)-1]; last.Type != "batch_complete" {
		t.Fatalf("last event = %+v, want batch_complete", last)
	}
}

func TestSequentialRawJobUploadsOneFileAtATimeInListOrder(t *testing.T) {
	var mu sync.Mutex
	active, peak := 0, 0
	var order []string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		active++
		if active > peak {
			peak = active
		}
		mu.Unlock()
		_, header, err := r.FormFile("image")
		time.Sleep(15 * time.Millisecond)
		mu.Lock()
		active--
		if err == nil {
			order = append(order, header.Filename)
		}
		mu.Unlock()
		_, _ = w.Write([]byte("ok"))
	}))
	defer server.Close()
	useSharedClient(t)

	names := []string{"e.jpg", "c.jpg", "a.jpg", "d.jpg", "b.jpg"}
	job := asRawJob(JobRequest{ID: "raw-seq", Action: "http_upload", Service: "raw-seq.test",
		Files: writeNamedFiles(t, names...), Config: map[string]string{"threads": "4"}}, server.URL)
	job.Sequential = true

	events := captureSidecarEvents(t, func() { handleJob(job) })

	if peak != 1 {
		t.Fatalf("peak concurrent uploads = %d, want 1 for a sequential job", peak)
	}
	if strings.Join(order, ",") != strings.Join(names, ",") {
		t.Fatalf("upload order %v, want list order %v", order, names)
	}
	if got := len(eventsOfType(events, "result")); got != len(names) {
		t.Fatalf("raw results = %d, want %d", got, len(names))
	}
}

func TestRawUploadJobUsesItsSessionCookies(t *testing.T) {
	useSharedClient(t)
	host := cookieHost(t)
	sessionID := openSessionAction(t, "b-raw-session")
	sessionRequest(t, "login", sessionID, host.URL+"/set?v=logged-in")

	files := writeNamedFiles(t, "a.jpg")
	job := asRawJob(JobRequest{ID: "raw-session", BatchID: "b-raw-session", Action: "http_upload",
		Service: "raw-session.test", Files: files}, host.URL+"/upload")
	job.SessionID = sessionID
	events := captureSidecarEvents(t, func() { handleJob(job) })
	results := eventsOfType(events, "result")
	if len(results) != 1 || dataString(results[0], "response_body") != `{"cookie":"logged-in"}` {
		t.Fatalf("upload on the session saw %+v, want the session cookie", results)
	}

	shared := asRawJob(JobRequest{ID: "raw-shared", Action: "http_upload", Service: "raw-session.test", Files: files}, host.URL+"/upload")
	events = captureSidecarEvents(t, func() { handleJob(shared) })
	if results := eventsOfType(events, "result"); len(results) != 1 || dataString(results[0], "response_body") != `{"cookie":"none"}` {
		t.Fatalf("upload without a session saw %+v, want no cookie", results)
	}
}

func TestUploadJobWithUnknownSessionFailsEveryFile(t *testing.T) {
	useSharedClient(t)
	files := writeNamedFiles(t, "a.jpg", "b.jpg")
	job := asRawJob(JobRequest{ID: "raw-nosession", Action: "http_upload", Service: "raw-nosession.test", Files: files},
		"http://unused.test/upload")
	job.SessionID = "s-gone"

	events := captureSidecarEvents(t, func() { handleJob(job) })
	for _, fp := range files {
		fileEvents := eventsForFile(events, fp)
		if len(fileEvents) != 2 || fileEvents[0].Status != "Failed" || fileEvents[1].Msg != "unknown transport session" {
			t.Fatalf("%s events = %+v", fp, fileEvents)
		}
	}
	if last := events[len(events)-1]; last.Type != "batch_complete" {
		t.Fatalf("last event = %+v, want batch_complete", last)
	}
}

func TestCancelAbortsAnInFlightRawUpload(t *testing.T) {
	received := make(chan struct{})
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		close(received)
		select {
		case <-release:
		case <-r.Context().Done():
		}
	}))
	defer server.Close()
	defer close(release)
	useSharedClient(t)

	sessionID := openSessionAction(t, "b-raw-cancel")
	files := writeNamedFiles(t, "a.jpg")
	job := asRawJob(JobRequest{ID: "raw-cancel", BatchID: "b-raw-cancel", Action: "http_upload",
		Service: "raw-cancel.test", Files: files}, server.URL)
	job.SessionID = sessionID

	events := captureSidecarEvents(t, func() {
		done := make(chan struct{})
		go func() {
			defer close(done)
			handleJob(job)
		}()
		select {
		case <-received:
		case <-time.After(5 * time.Second):
			t.Error("upload never reached the host")
			return
		}
		handleJob(JobRequest{Action: "cancel", BatchID: "b-raw-cancel"})
		select {
		case <-done:
		case <-time.After(5 * time.Second):
			t.Error("raw upload did not end after cancel")
		}
	})
	fileEvents := eventsForFile(events, files[0])
	if len(fileEvents) < 2 || fileEvents[len(fileEvents)-2].Status != "Cancelled" {
		t.Fatalf("events = %+v, want Cancelled", fileEvents)
	}
	if results := eventsOfType(events, "result"); len(results) != 0 {
		t.Fatalf("a cancelled raw upload reported a result: %+v", results)
	}
}

// Raw jobs count against the same per-service upload limit as every job.
func TestRawUploadJobsShareTheServiceLimiter(t *testing.T) {
	g := newGateHost(t)
	first := asRawJob(limiterJob(t, g.server.URL, "raw-limiter.test", "/first", 3, 2), g.server.URL+"/first")
	second := asRawJob(limiterJob(t, g.server.URL, "raw-limiter.test", "/second", 3, 2), g.server.URL+"/second")

	events := runJobsWithGate(t, g, func(start func(JobRequest)) {
		start(first)
		g.waitInFlight(t, 2)
		start(second)
		time.Sleep(50 * time.Millisecond)
		if total, _, _ := g.counts(); total != 2 {
			t.Errorf("uploads in flight = %d, want 2 (Thread Limit)", total)
		}
		for i := 0; i < 4; i++ {
			g.release <- struct{}{}
		}
	})
	if _, _, peak := g.counts(); peak > 2 {
		t.Fatalf("peak concurrency = %d, want at most 2", peak)
	}
	if got := len(eventsOfType(events, "result")); got != 6 {
		t.Fatalf("raw results = %d, want 6", got)
	}
	uploaded := 0
	for _, event := range eventsOfType(events, "status") {
		if event.Status == "Uploaded" {
			uploaded++
		}
	}
	if uploaded != 6 {
		t.Fatalf("Uploaded statuses = %d, want 6", uploaded)
	}
}

func TestRawUploadJobDoesNotNeedAnHTTPSpec(t *testing.T) {
	events := runAction(t, JobRequest{ID: "raw-nospec", Action: "http_upload", Service: "raw.test",
		Files: writeNamedFiles(t, "a.jpg"), RawResponse: true})
	for _, event := range events {
		if event.Type == "error" && event.FilePath == "" {
			t.Fatalf("raw job rejected as a whole: %+v", event)
		}
	}
	if fmt.Sprint(events[len(events)-1].Type) != "batch_complete" {
		t.Fatalf("raw job without requests did not complete: %+v", events)
	}
}

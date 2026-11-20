// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/conniecombs/GolangVersion/core"
)

// A raw upload job that waits in the upload queue longer than SessionIdleTTL
// keeps its transport session: the session is in use from the moment the
// stdin reader queues a job that names it, not only once the job starts.
func TestQueuedRawJobKeepsItsSessionPastTheIdleTTL(t *testing.T) {
	useSharedClient(t)
	oldTTL := core.SessionIdleTTL
	core.SessionIdleTTL = 300 * time.Millisecond
	t.Cleanup(func() { core.SessionIdleTTL = oldTTL })
	batchID := uniqueBatchID("reap-queued")

	busyStarted := make(chan struct{}, 4)
	release := make(chan struct{})
	busy := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		busyStarted <- struct{}{}
		select {
		case <-release:
		case <-r.Context().Done():
		}
		_, _ = w.Write([]byte(`{"ok":1}`))
	}))
	defer busy.Close()
	host := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		_, _ = w.Write([]byte(`{"url":"https://img.example/v"}`))
	}))
	defer host.Close()

	// Job A: an earlier group's upload that keeps the only upload worker busy.
	files := writeNamedFiles(t, "a.jpg", "b.jpg")
	jobA := asRawJob(JobRequest{ID: "group-1", BatchID: batchID, Action: "http_upload",
		Service: "reap.test", Files: files[:1], Config: map[string]string{"threads": "1"}}, busy.URL+"/upload")
	lineA, _ := json.Marshal(jobA)
	openLine, _ := json.Marshal(JobRequest{ID: "open-2", Action: "session_open", BatchID: batchID})

	input, feed := io.Pipe()
	streamSidecarEvents(t, func(events <-chan OutputEvent) {
		done := make(chan struct{})
		go func() {
			defer close(done)
			runSidecar(input, 1, make(chan struct{}))
		}()
		defer func() {
			_ = feed.Close()
			select {
			case <-done:
			case <-time.After(10 * time.Second):
				t.Error("sidecar did not shut down")
			}
		}()
		_, _ = feed.Write(append(lineA, '\n'))
		<-busyStarted

		// Group 2 opens its session (and logs in) at dispatch time, then sends
		// its raw job, which queues behind group 1.
		_, _ = feed.Write(append(openLine, '\n'))
		var sessionID string
		deadline := time.After(5 * time.Second)
		for sessionID == "" {
			select {
			case event := <-events:
				if event.ID == "open-2" && event.Type == "result" {
					sessionID = dataString(event, "session_id")
				}
			case <-deadline:
				t.Fatal("no session")
			}
		}
		jobB := asRawJob(JobRequest{ID: "group-2", BatchID: batchID, Action: "http_upload",
			Service: "reap.test", Files: files[1:], Config: map[string]string{"threads": "1"},
			SessionID: sessionID}, host.URL+"/upload")
		lineB, _ := json.Marshal(jobB)
		_, _ = feed.Write(append(lineB, '\n'))

		// Group 1 takes longer than the idle TTL (30 minutes in production);
		// the reaper runs meanwhile.
		time.Sleep(2 * core.SessionIdleTTL)
		core.ReapIdleSessions()
		close(release)

		deadline = time.After(5 * time.Second)
		for {
			select {
			case event := <-events:
				if event.ID != "group-2" || event.FilePath != files[1] {
					continue
				}
				switch event.Type {
				case "result":
					if got := dataString(event, "status_code"); got != "200" {
						t.Fatalf("group 2 result = %+v", event)
					}
					return
				case "error":
					t.Fatalf("group 2's queued job lost its session: %q", event.Msg)
				}
			case <-deadline:
				t.Fatal("no answer for group 2")
			}
		}
	})

	// Once the job has ended the session is idle again and the reaper may
	// close it after a full TTL.
	time.Sleep(2 * core.SessionIdleTTL)
	if n := core.ReapIdleSessions(); n < 1 {
		t.Fatalf("reaped %d sessions after the job ended, want the job's session", n)
	}
}

// A job whose session is gone by the time it is read still fails each file
// with "unknown transport session"; holding a missing session holds nothing.
func TestQueuedRawJobWithAnUnknownSessionStillFails(t *testing.T) {
	useSharedClient(t)
	files := writeNamedFiles(t, "gone.jpg")
	job := asRawJob(JobRequest{ID: "gone", BatchID: uniqueBatchID("reap-gone"), Action: "http_upload",
		Service: "reap.test", Files: files, SessionID: "s-not-open"}, "http://127.0.0.1:1/upload")
	line, _ := json.Marshal(job)

	events := captureSidecarEvents(t, func() {
		runSidecar(strings.NewReader(string(line)+"\n"), 1, make(chan struct{}))
	})
	for _, event := range eventsForFile(events, files[0]) {
		if event.Type == "error" {
			if !strings.Contains(event.Msg, "unknown transport session") {
				t.Fatalf("error = %q, want unknown transport session", event.Msg)
			}
			return
		}
	}
	t.Fatalf("no error for the file: %+v", events)
}

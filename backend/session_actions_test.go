// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package main

import (
	"bufio"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/conniecombs/GolangVersion/core"
)

// runAction runs one job through handleJob and returns its events.
func runAction(t *testing.T, job JobRequest) []OutputEvent {
	t.Helper()
	return captureSidecarEvents(t, func() { handleJob(job) })
}

func resultFor(t *testing.T, events []OutputEvent, id string) OutputEvent {
	t.Helper()
	for _, event := range events {
		if event.ID == id && event.Type == "result" {
			return event
		}
	}
	t.Fatalf("no result event for %q in %+v", id, events)
	return OutputEvent{}
}

func dataString(event OutputEvent, key string) string {
	data, _ := event.Data.(map[string]interface{})
	value, _ := data[key].(string)
	return value
}

func openSessionAction(t *testing.T, batchID string) string {
	t.Helper()
	event := resultFor(t, runAction(t, JobRequest{ID: "open-" + batchID, Action: "session_open", BatchID: batchID}), "open-"+batchID)
	if event.Status != "success" {
		t.Fatalf("session_open failed: %+v", event)
	}
	sessionID := dataString(event, "session_id")
	if !strings.HasPrefix(sessionID, "s-") {
		t.Fatalf("session_id = %q", sessionID)
	}
	return sessionID
}

func sessionRequest(t *testing.T, id, sessionID, url string) OutputEvent {
	t.Helper()
	job := JobRequest{ID: id, Action: "http_request", Service: "session.test", GenericSpec: &core.GenericHttpRequestSpec{
		URL: url, Method: http.MethodGet, UseCookies: true, IncludeResponseBody: true, SessionID: sessionID,
	}}
	return resultFor(t, runAction(t, job), id)
}

func cookieHost(t *testing.T) *httptest.Server {
	t.Helper()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/set":
			http.SetCookie(w, &http.Cookie{Name: "sid", Value: r.URL.Query().Get("v"), Path: "/"})
			_, _ = w.Write([]byte("set"))
		case "/get":
			value := "none"
			if c, err := r.Cookie("sid"); err == nil {
				value = c.Value
			}
			_, _ = w.Write([]byte(value))
		case "/upload":
			_, _ = io.Copy(io.Discard, r.Body)
			value := "none"
			if c, err := r.Cookie("sid"); err == nil {
				value = c.Value
			}
			_, _ = w.Write([]byte(`{"cookie":"` + value + `"}`))
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(server.Close)
	return server
}

func useSharedClient(t *testing.T) {
	t.Helper()
	oldClient := client
	client = &http.Client{Jar: core.NewSwappableJar()}
	t.Cleanup(func() { client = oldClient })
}

func TestSessionActionsKeepCookiesApart(t *testing.T) {
	useSharedClient(t)
	host := cookieHost(t)

	first := openSessionAction(t, "b-sess-1")
	second := openSessionAction(t, "b-sess-1")

	sessionRequest(t, "set-1", first, host.URL+"/set?v=one")
	sessionRequest(t, "set-2", second, host.URL+"/set?v=two")
	resultFor(t, runAction(t, JobRequest{ID: "set-shared", Action: "http_request", Service: "session.test",
		GenericSpec: &core.GenericHttpRequestSpec{URL: host.URL + "/set?v=shared", UseCookies: true}}), "set-shared")

	if got := dataString(sessionRequest(t, "get-1", first, host.URL+"/get"), "response_body"); got != "one" {
		t.Fatalf("first session sees %q, want one", got)
	}
	if got := dataString(sessionRequest(t, "get-2", second, host.URL+"/get"), "response_body"); got != "two" {
		t.Fatalf("second session sees %q, want two", got)
	}
	shared := resultFor(t, runAction(t, JobRequest{ID: "get-shared", Action: "http_request", Service: "session.test",
		GenericSpec: &core.GenericHttpRequestSpec{URL: host.URL + "/get", UseCookies: true, IncludeResponseBody: true}}), "get-shared")
	if got := dataString(shared, "response_body"); got != "shared" {
		t.Fatalf("shared jar sees %q, want shared", got)
	}

	closeEvent := resultFor(t, runAction(t, JobRequest{ID: "close-1", Action: "session_close", SessionID: first}), "close-1")
	if closeEvent.Status != "success" || dataString(closeEvent, "closed") != "true" {
		t.Fatalf("session_close = %+v", closeEvent)
	}
	after := sessionRequest(t, "get-closed", first, host.URL+"/get")
	if after.Status != "failed" || !strings.Contains(after.Msg, "unknown transport session") {
		t.Fatalf("request on a closed session = %+v, want unknown transport session", after)
	}
}

func TestCancelClosesTheBatchSessions(t *testing.T) {
	useSharedClient(t)
	host := cookieHost(t)
	batchID := uniqueBatchID("b-sess-cancel")
	sessionID := openSessionAction(t, batchID)

	runAction(t, JobRequest{Action: "cancel", BatchID: batchID})

	event := sessionRequest(t, "after-cancel", sessionID, host.URL+"/get")
	if event.Status != "failed" || !strings.Contains(event.Msg, "unknown transport session") {
		t.Fatalf("request after cancel = %+v, want unknown transport session", event)
	}
	reopen := resultFor(t, runAction(t, JobRequest{ID: "reopen", Action: "session_open", BatchID: batchID}), "reopen")
	if reopen.Status != "failed" {
		t.Fatalf("session_open for a cancelled batch = %+v, want failed", reopen)
	}
}

func TestSessionCloseWithoutIDOnlyLogs(t *testing.T) {
	sessionID := openSessionAction(t, "b-sess-noid")
	events := runAction(t, JobRequest{Action: "session_close", SessionID: sessionID})
	for _, event := range events {
		if event.Type == "result" {
			t.Fatalf("session_close without an id emitted a result: %+v", event)
		}
	}
	if _, _, err := core.AcquireSession(sessionID); err == nil {
		t.Fatal("session_close without an id did not close the session")
	}
}

func TestSessionCloseRequiresSessionID(t *testing.T) {
	events := runAction(t, JobRequest{ID: "close-none", Action: "session_close"})
	if len(events) == 0 || events[0].Type != "error" || !strings.Contains(events[0].Msg, "session_id") {
		t.Fatalf("events = %+v, want an invalid job error naming session_id", events)
	}
}

// streamSidecarEvents redirects stdout while fn runs and delivers each event
// on the channel as soon as it is printed.
func streamSidecarEvents(t *testing.T, fn func(events <-chan OutputEvent)) {
	t.Helper()
	oldStdout := os.Stdout
	reader, writer, err := os.Pipe()
	if err != nil {
		t.Fatalf("os.Pipe: %v", err)
	}
	os.Stdout = writer
	events := make(chan OutputEvent, 1024)
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		scanner := bufio.NewScanner(reader)
		scanner.Buffer(make([]byte, 0, 1024*1024), 16*1024*1024)
		for scanner.Scan() {
			var event OutputEvent
			if json.Unmarshal(scanner.Bytes(), &event) == nil {
				select {
				case events <- event:
				default:
				}
			}
		}
	}()
	defer func() {
		_ = writer.Close()
		os.Stdout = oldStdout
		wg.Wait()
		_ = reader.Close()
	}()
	fn(events)
}

// Session actions run on the request pool, so a session opens while every
// upload worker is busy.
func TestSessionOpenIsNotQueuedBehindUploads(t *testing.T) {
	useSharedClient(t)
	uploadStarted := make(chan struct{}, 4)
	release := make(chan struct{})
	uploads := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		uploadStarted <- struct{}{}
		select {
		case <-release:
		case <-r.Context().Done():
		}
		_, _ = w.Write([]byte(`{"data":{"image_url":"u","thumbnail_url":"t"}}`))
	}))
	defer uploads.Close()

	upload := uploadJobForServer(t, uploads.URL, "pool-sess")
	upload.ID = "busy-upload"
	uploadLine, _ := json.Marshal(upload)
	openLine, _ := json.Marshal(JobRequest{ID: "open-busy", Action: "session_open", BatchID: "pool-sess-open"})

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
		_, _ = feed.Write(append(uploadLine, '\n'))
		select {
		case <-uploadStarted:
		case <-time.After(5 * time.Second):
			t.Error("upload worker never got busy")
			return
		}
		_, _ = feed.Write(append(openLine, '\n'))
		deadline := time.After(3 * time.Second)
		for {
			select {
			case event := <-events:
				if event.ID == "open-busy" && event.Type == "result" {
					if event.Status != "success" {
						t.Errorf("session_open = %+v", event)
					}
					return
				}
			case <-deadline:
				t.Error("session_open did not answer while the upload worker was busy")
				return
			}
		}
	})
}

// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// cookieEchoServer sets cookie sid=<v> on /set?v=<v> and echoes the sid cookie
// it receives on /get.
func cookieEchoServer(t *testing.T) *httptest.Server {
	t.Helper()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/set":
			http.SetCookie(w, &http.Cookie{Name: "sid", Value: r.URL.Query().Get("v"), Path: "/"})
			_, _ = w.Write([]byte("set"))
		case "/get":
			if c, err := r.Cookie("sid"); err == nil {
				_, _ = w.Write([]byte(c.Value))
			}
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(server.Close)
	return server
}

func getBody(t *testing.T, client *http.Client, url string) string {
	t.Helper()
	resp, err := client.Get(url)
	if err != nil {
		t.Fatalf("GET %s: %v", url, err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	return string(body)
}

func resetSessions(t *testing.T) {
	t.Helper()
	t.Cleanup(func() {
		sessionsMu.Lock()
		for id, s := range sessions {
			s.close()
			delete(sessions, id)
		}
		sessionsMu.Unlock()
	})
}

func TestSessionsKeepCookiesApartFromEachOtherAndTheSharedJar(t *testing.T) {
	resetSessions(t)
	server := cookieEchoServer(t)
	shared := &http.Client{Jar: NewSwappableJar()}

	a, err := OpenSession(shared, "batch-cookies")
	if err != nil {
		t.Fatalf("open a: %v", err)
	}
	b, err := OpenSession(shared, "batch-cookies")
	if err != nil {
		t.Fatalf("open b: %v", err)
	}
	if a.ID == b.ID || !strings.HasPrefix(a.ID, "s-") {
		t.Fatalf("session ids %q and %q must be distinct and start with s-", a.ID, b.ID)
	}

	getBody(t, a.Client, server.URL+"/set?v=alpha")
	getBody(t, b.Client, server.URL+"/set?v=beta")
	getBody(t, shared, server.URL+"/set?v=shared")

	if got := getBody(t, a.Client, server.URL+"/get"); got != "alpha" {
		t.Fatalf("session a sees cookie %q, want alpha", got)
	}
	if got := getBody(t, b.Client, server.URL+"/get"); got != "beta" {
		t.Fatalf("session b sees cookie %q, want beta", got)
	}
	if got := getBody(t, shared, server.URL+"/get"); got != "shared" {
		t.Fatalf("shared jar sees cookie %q, want shared", got)
	}
	if a.Client.Jar == shared.Jar || b.Client.Jar == shared.Jar {
		t.Fatal("a session must never use the shared cookie jar")
	}
	if a.Client.Transport != shared.Transport {
		t.Fatal("a session client must share the global transport")
	}
}

func TestUnknownOrClosedSessionIsReported(t *testing.T) {
	resetSessions(t)
	if _, _, err := AcquireSession("s-does-not-exist"); !errors.Is(err, ErrUnknownSession) {
		t.Fatalf("err = %v, want ErrUnknownSession", err)
	}
	if ErrUnknownSession.Error() != "unknown transport session" {
		t.Fatalf("message = %q", ErrUnknownSession.Error())
	}

	s, err := OpenSession(nil, "")
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	if !CloseSession(s.ID) {
		t.Fatal("CloseSession = false for an open session")
	}
	if CloseSession(s.ID) {
		t.Fatal("CloseSession = true for an already closed session")
	}
	if _, _, err := AcquireSession(s.ID); !errors.Is(err, ErrUnknownSession) {
		t.Fatalf("closed session: err = %v, want ErrUnknownSession", err)
	}
	if !s.Closed() || s.Context().Err() == nil {
		t.Fatal("a closed session's context must be done")
	}
}

func TestCancellingABatchClosesOnlyItsSessions(t *testing.T) {
	resetSessions(t)
	mine, _ := OpenSession(nil, "batch-close-mine")
	other, _ := OpenSession(nil, "batch-close-other")

	if n := CloseBatchSessions("batch-close-mine"); n != 1 {
		t.Fatalf("closed %d sessions, want 1", n)
	}
	if _, _, err := AcquireSession(mine.ID); !errors.Is(err, ErrUnknownSession) {
		t.Fatalf("session of the cancelled batch is still open: %v", err)
	}
	if _, release, err := AcquireSession(other.ID); err != nil {
		t.Fatalf("session of another batch was closed: %v", err)
	} else {
		release()
	}
	if CloseBatchSessions("") != 0 {
		t.Fatal("an empty batch id must close nothing")
	}
}

func TestSessionCannotOpenForACancelledBatch(t *testing.T) {
	resetSessions(t)
	CancelBatch("batch-cancelled-before-open")
	if _, err := OpenSession(nil, "batch-cancelled-before-open"); err == nil {
		t.Fatal("opened a session for a cancelled batch")
	}
	sessionsMu.Lock()
	defer sessionsMu.Unlock()
	for _, s := range sessions {
		if s.BatchID == "batch-cancelled-before-open" {
			t.Fatal("a session of a cancelled batch was left registered")
		}
	}
}

func TestIdleSessionsAreReapedButBusyOnesAreNot(t *testing.T) {
	resetSessions(t)
	old := SessionIdleTTL
	SessionIdleTTL = 50 * time.Millisecond
	t.Cleanup(func() { SessionIdleTTL = old })

	idle, _ := OpenSession(nil, "batch-reap")
	busy, _ := OpenSession(nil, "batch-reap")
	_, releaseBusy, err := AcquireSession(busy.ID)
	if err != nil {
		t.Fatalf("acquire busy: %v", err)
	}

	time.Sleep(120 * time.Millisecond)
	if n := ReapIdleSessions(); n != 1 {
		t.Fatalf("reaped %d sessions, want 1 (the idle one)", n)
	}
	if !idle.Closed() {
		t.Fatal("the idle session was not closed")
	}
	if busy.Closed() {
		t.Fatal("a session in use was reaped")
	}

	// Release marks it used now, so it survives until a full idle TTL passes.
	releaseBusy()
	if n := ReapIdleSessions(); n != 0 {
		t.Fatalf("reaped %d sessions right after use, want 0", n)
	}
	time.Sleep(120 * time.Millisecond)
	// Looking a session up prunes idle sessions too.
	if _, _, err := AcquireSession(busy.ID); !errors.Is(err, ErrUnknownSession) {
		t.Fatalf("idle session survived its TTL: %v", err)
	}
}

func TestClosingASessionAbortsItsInFlightRequest(t *testing.T) {
	resetSessions(t)
	started := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(started)
		<-r.Context().Done()
	}))
	defer server.Close()

	s, _ := OpenSession(nil, "batch-abort")
	done := make(chan error, 1)
	go func() {
		ctx, cancel := context.WithTimeout(s.Context(), 10*time.Second)
		defer cancel()
		req, _ := http.NewRequestWithContext(ctx, http.MethodGet, server.URL, nil)
		resp, err := s.Client.Do(req)
		if err == nil {
			_ = resp.Body.Close()
		}
		done <- err
	}()
	<-started
	CloseBatchSessions("batch-abort")
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("request on a closed session succeeded")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("closing the session did not abort its request")
	}
	if !errors.Is(context.Cause(s.Context()), ErrSessionClosed) {
		t.Fatalf("cause = %v, want ErrSessionClosed", context.Cause(s.Context()))
	}
}

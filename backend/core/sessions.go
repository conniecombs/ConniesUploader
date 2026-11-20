// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"errors"
	"net/http"
	"sync"
	"time"
)

// A transport session is a named, isolated cookie jar plus an *http.Client
// that shares the global transport (connection reuse, TLS, timeouts). Python
// opens one per upload job (session_open), runs a host's login and follow-up
// requests on it (generic_spec.session_id) and uploads with it (http_upload
// session_id), then closes it (session_close). A session never touches the
// shared cookie jar.

var (
	// ErrUnknownSession reports a session id that is not open (never opened,
	// closed, reaped, or opened by an earlier sidecar process).
	ErrUnknownSession = errors.New("unknown transport session")
	// ErrSessionClosed is the cause of a session context ended by a close.
	ErrSessionClosed = errors.New("transport session closed")
	// ErrBatchCancelled reports a session_open for a batch already cancelled.
	ErrBatchCancelled = errors.New("batch cancelled")
)

// SessionIdleTTL is how long a session may sit unused before it is reaped:
// counted from the end of its last use, and never while it is in use (an
// upload job naming it is queued or running, or a request runs on it).
// A variable so tests can shrink it.
var SessionIdleTTL = 30 * time.Minute

// sessionReapInterval is how often the background reaper looks for idle
// sessions; lookups and opens also prune them.
const sessionReapInterval = time.Minute

// TransportSession is one open session.
type TransportSession struct {
	ID      string
	BatchID string
	// Client has the session's own cookie jar and the global transport.
	Client *http.Client

	ctx    context.Context
	cancel context.CancelCauseFunc

	// Guarded by sessionsMu.
	active   int
	lastUsed time.Time
	closed   bool
}

var (
	sessionsMu        sync.Mutex
	sessions          = map[string]*TransportSession{}
	sessionReaperOnce sync.Once
)

// Context is done once the session is closed, so requests made with a
// context derived from it are aborted by a close or a batch cancel.
func (s *TransportSession) Context() context.Context { return s.ctx }

// Closed reports whether the session has been closed.
func (s *TransportSession) Closed() bool {
	sessionsMu.Lock()
	defer sessionsMu.Unlock()
	return s.closed
}

// close ends the session's context. Callers hold sessionsMu or own s alone.
// The transport is shared, so its pooled connections stay open.
func (s *TransportSession) close() {
	s.closed = true
	s.cancel(ErrSessionClosed)
}

// newSessionClient copies base's transport, redirect policy and timeout and
// gives the copy a fresh cookie jar of its own.
func newSessionClient(base *http.Client) *http.Client {
	client := &http.Client{Timeout: ClientTimeout, Jar: NewSwappableJar()}
	if base != nil {
		client.Transport = base.Transport
		client.CheckRedirect = base.CheckRedirect
		client.Timeout = base.Timeout
	}
	return client
}

// OpenSession opens a session for batchID (which may be empty). It fails
// with ErrBatchCancelled when the batch was cancelled, including a cancel
// that races with the open.
func OpenSession(base *http.Client, batchID string) (*TransportSession, error) {
	if BatchCancelled(batchID) {
		return nil, ErrBatchCancelled
	}
	ctx, cancel := context.WithCancelCause(context.Background())
	session := &TransportSession{
		ID:       "s-" + RandomString(24),
		BatchID:  batchID,
		Client:   newSessionClient(base),
		ctx:      ctx,
		cancel:   cancel,
		lastUsed: time.Now(),
	}
	sessionsMu.Lock()
	reapIdleLocked(time.Now())
	sessions[session.ID] = session
	sessionsMu.Unlock()

	// A cancel marks the batch before closing its sessions, so a cancel that
	// missed this session while it was being registered is seen here.
	if BatchCancelled(batchID) {
		CloseSession(session.ID)
		return nil, ErrBatchCancelled
	}
	return session, nil
}

// AcquireSession returns an open session and marks it in use until release
// is called. A session in use is never reaped; release counts as a use.
func AcquireSession(id string) (*TransportSession, func(), error) {
	sessionsMu.Lock()
	defer sessionsMu.Unlock()
	reapIdleLocked(time.Now())
	session := sessions[id]
	if session == nil || session.closed {
		return nil, func() {}, ErrUnknownSession
	}
	return session, useLocked(session), nil
}

// HoldSession marks session id in use until release is called, without
// looking it up for use. The stdin reader holds the session of every queued
// http_upload job that names one, so a job waiting behind other uploads for
// longer than SessionIdleTTL still finds its session. Holding a session that
// is not open holds nothing; the job then fails with ErrUnknownSession when
// it starts. A close or a batch cancel still closes a held session.
func HoldSession(id string) (release func()) {
	sessionsMu.Lock()
	defer sessionsMu.Unlock()
	session := sessions[id]
	if id == "" || session == nil || session.closed {
		return func() {}
	}
	return useLocked(session)
}

// useLocked counts one use of session and returns the func that ends it.
// Callers hold sessionsMu.
func useLocked(session *TransportSession) func() {
	session.active++
	session.lastUsed = time.Now()
	var once sync.Once
	return func() {
		once.Do(func() {
			sessionsMu.Lock()
			defer sessionsMu.Unlock()
			session.active--
			session.lastUsed = time.Now()
		})
	}
}

// CloseSession closes one session and reports whether it was open.
func CloseSession(id string) bool {
	sessionsMu.Lock()
	defer sessionsMu.Unlock()
	session := sessions[id]
	if session == nil {
		return false
	}
	delete(sessions, id)
	session.close()
	return true
}

// CloseBatchSessions closes every session of batchID and returns how many
// were open. An empty batch id closes nothing.
func CloseBatchSessions(batchID string) int {
	if batchID == "" {
		return 0
	}
	sessionsMu.Lock()
	defer sessionsMu.Unlock()
	closed := 0
	for id, session := range sessions {
		if session.BatchID == batchID {
			delete(sessions, id)
			session.close()
			closed++
		}
	}
	return closed
}

// ReapIdleSessions closes sessions unused for SessionIdleTTL and returns how
// many it closed.
func ReapIdleSessions() int {
	sessionsMu.Lock()
	defer sessionsMu.Unlock()
	return reapIdleLocked(time.Now())
}

func reapIdleLocked(now time.Time) int {
	reaped := 0
	for id, session := range sessions {
		if session.active == 0 && now.Sub(session.lastUsed) >= SessionIdleTTL {
			delete(sessions, id)
			session.close()
			reaped++
		}
	}
	return reaped
}

// StartSessionReaper starts, once per process, a goroutine that reaps idle
// sessions even when no session is opened or looked up.
func StartSessionReaper() {
	sessionReaperOnce.Do(func() {
		go func() {
			ticker := time.NewTicker(sessionReapInterval)
			defer ticker.Stop()
			for range ticker.C {
				ReapIdleSessions()
			}
		}()
	})
}

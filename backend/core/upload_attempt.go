// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptrace"
	"sync"
	"sync/atomic"
	"time"
)

var (
	errUploadStalled    = errors.New("upload stalled")
	errUploadNoResponse = errors.New("no response after upload")
)

// uploadStallError reports an upload whose body stopped moving before it was
// fully sent. The host cannot have stored a partial body, so it is retryable
// (it is a timeout in net.Error terms).
type uploadStallError struct{ after time.Duration }

func (e *uploadStallError) Error() string {
	return fmt.Sprintf("upload stalled: no data sent for %s", e.after)
}
func (e *uploadStallError) Timeout() bool   { return true }
func (e *uploadStallError) Temporary() bool { return true }

// uploadAttempt bounds one upload request without a wall-clock limit:
//   - until the body is sent, the attempt is cancelled when the transport
//     reads no body bytes for stallTimeout;
//   - once the body is sent (or a response arrives first), the attempt is
//     cancelled when the response is not complete within responseTimeout.
//
// It also records whether the body was fully written, so a failure after
// that point is reported as a lost response and never retried: the host may
// already have stored the file.
type uploadAttempt struct {
	parent          context.Context
	ctx             context.Context
	cancel          context.CancelCauseFunc
	stallTimeout    time.Duration
	responseTimeout time.Duration

	lastProgress atomic.Int64 // UnixNano of the last body read
	bodySent     atomic.Bool
	gotResponse  atomic.Bool

	mu            sync.Mutex
	ended         bool
	stallTimer    *time.Timer
	responseTimer *time.Timer
}

func newUploadAttempt(parent context.Context) *uploadAttempt {
	ctx, cancel := context.WithCancelCause(parent)
	a := &uploadAttempt{
		parent:          parent,
		cancel:          cancel,
		stallTimeout:    UploadStallTimeout,
		responseTimeout: UploadResponseTimeout,
	}
	a.ctx = httptrace.WithClientTrace(ctx, &httptrace.ClientTrace{WroteRequest: a.wroteRequest})
	a.touch()
	a.mu.Lock()
	a.stallTimer = time.AfterFunc(a.stallTimeout, a.checkStall)
	a.mu.Unlock()
	return a
}

func (a *uploadAttempt) touch() { a.lastProgress.Store(time.Now().UnixNano()) }

// checkStall runs on the stall timer: it cancels the attempt when the body
// has not moved for stallTimeout, and otherwise re-arms for the remainder.
func (a *uploadAttempt) checkStall() {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.ended || a.responseTimer != nil {
		return
	}
	idle := time.Since(time.Unix(0, a.lastProgress.Load()))
	if idle >= a.stallTimeout {
		a.cancel(errUploadStalled)
		return
	}
	a.stallTimer.Reset(a.stallTimeout - idle)
}

// startResponseWait swaps the stall watchdog for the bounded response wait.
func (a *uploadAttempt) startResponseWait() {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.ended || a.responseTimer != nil {
		return
	}
	a.stallTimer.Stop()
	a.responseTimer = time.AfterFunc(a.responseTimeout, func() { a.cancel(errUploadNoResponse) })
}

func (a *uploadAttempt) wroteRequest(info httptrace.WroteRequestInfo) {
	if info.Err != nil {
		return
	}
	a.bodySent.Store(true)
	a.startResponseWait()
}

// body wraps the request body so every read counts as progress.
func (a *uploadAttempt) body(r io.ReadCloser) io.ReadCloser {
	return &progressBody{ReadCloser: r, attempt: a}
}

type progressBody struct {
	io.ReadCloser
	attempt *uploadAttempt
}

func (b *progressBody) Read(p []byte) (int, error) {
	n, err := b.ReadCloser.Read(p)
	if n > 0 {
		b.attempt.touch()
	}
	return n, err
}

// do sends req with client minus its whole-request Timeout and its
// transport's response-header timeout; this attempt's own limits apply
// instead.
func (a *uploadAttempt) do(client *http.Client, req *http.Request) (*http.Response, error) {
	if client != nil {
		transfer := *client
		transfer.Timeout = 0
		transfer.Transport = uploadTransport(client.Transport)
		client = &transfer
	}
	resp, err := client.Do(req)
	if err == nil {
		a.gotResponse.Store(true)
		a.startResponseWait()
	}
	return resp, err
}

// uploadTransports caches, per shared transport, a clone without
// ResponseHeaderTimeout, so uploads keep pooled connections of their own.
var uploadTransports sync.Map // *http.Transport -> *http.Transport

// uploadTransport returns rt for upload requests. When the transport has
// finished writing the body, the last of it can still be queued in OS
// buffers on a slow uplink, so a short header timeout counted from that
// moment would fail uploads the host is still receiving. Uploads use
// UploadResponseTimeout instead; other requests keep rt unchanged.
func uploadTransport(rt http.RoundTripper) http.RoundTripper {
	base, ok := rt.(*http.Transport)
	if !ok || base.ResponseHeaderTimeout == 0 {
		return rt
	}
	if cached, ok := uploadTransports.Load(base); ok {
		return cached.(*http.Transport)
	}
	clone := base.Clone()
	clone.ResponseHeaderTimeout = 0
	cached, _ := uploadTransports.LoadOrStore(base, clone)
	return cached.(*http.Transport)
}

// finish stops the timers, releases the attempt context and turns err into
// the error the retry loop should see.
func (a *uploadAttempt) finish(err error) error {
	a.mu.Lock()
	a.ended = true
	a.stallTimer.Stop()
	if a.responseTimer != nil {
		a.responseTimer.Stop()
	}
	a.mu.Unlock()
	cause := context.Cause(a.ctx)
	a.cancel(nil)

	if err == nil || a.parent.Err() != nil {
		// Job cancellation and deadlines are reported by the caller.
		return err
	}
	switch {
	case errors.Is(cause, errUploadStalled):
		return &uploadStallError{after: a.stallTimeout}
	case errors.Is(cause, errUploadNoResponse):
		return NoRetry(fmt.Errorf(
			"no response from host within %s after upload; check the host before retrying", a.responseTimeout))
	case a.bodySent.Load() && !a.gotResponse.Load():
		return NoRetry(fmt.Errorf("no response from host after upload; check the host before retrying: %w", err))
	}
	return err
}

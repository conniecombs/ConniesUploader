// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptrace"
	"sync/atomic"
)

// uploadAttempt tracks one upload request. It records whether the body was
// fully written, so a failure after that point is reported as a lost
// response and never retried: the host may already have stored the file.
type uploadAttempt struct {
	parent context.Context
	ctx    context.Context

	bodySent    atomic.Bool
	gotResponse atomic.Bool
}

func newUploadAttempt(parent context.Context) *uploadAttempt {
	a := &uploadAttempt{parent: parent}
	a.ctx = httptrace.WithClientTrace(parent, &httptrace.ClientTrace{WroteRequest: a.wroteRequest})
	return a
}

func (a *uploadAttempt) wroteRequest(info httptrace.WroteRequestInfo) {
	if info.Err == nil {
		a.bodySent.Store(true)
	}
}

// body returns the request body to send.
func (a *uploadAttempt) body(r io.ReadCloser) io.ReadCloser { return r }

func (a *uploadAttempt) do(client *http.Client, req *http.Request) (*http.Response, error) {
	resp, err := client.Do(req)
	if err == nil {
		a.gotResponse.Store(true)
	}
	return resp, err
}

// finish turns err into the error the retry loop should see.
func (a *uploadAttempt) finish(err error) error {
	if err == nil || a.parent.Err() != nil {
		// Job cancellation and deadlines are reported by the caller.
		return err
	}
	if a.bodySent.Load() && !a.gotResponse.Load() {
		return NoRetry(fmt.Errorf("no response from host after upload; check the host before retrying: %w", err))
	}
	return err
}

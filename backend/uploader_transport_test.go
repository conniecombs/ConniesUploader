// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package main

import (
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// deadlineRecorder answers every upload and records whether the request
// context carried a deadline.
type deadlineRecorder struct{ deadlines chan bool }

func (d deadlineRecorder) RoundTrip(req *http.Request) (*http.Response, error) {
	_, _ = io.Copy(io.Discard, req.Body)
	_ = req.Body.Close()
	_, hasDeadline := req.Context().Deadline()
	d.deadlines <- hasDeadline
	return &http.Response{
		StatusCode: http.StatusOK,
		Header:     http.Header{"Content-Type": {"application/json"}},
		Body:       io.NopCloser(strings.NewReader(`{"data":{"image_url":"u","thumbnail_url":"t"}}`)),
		Request:    req,
	}, nil
}

// An upload must not run under a wall-clock deadline: a big file on a slow
// uplink needs longer than any fixed limit. Stalls are caught instead.
func TestUploadRequestHasNoWallClockDeadline(t *testing.T) {
	path := filepath.Join(t.TempDir(), "img.jpg")
	if err := os.WriteFile(path, []byte("jpeg-bytes"), 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}
	recorder := deadlineRecorder{deadlines: make(chan bool, 1)}
	oldClient := client
	client = &http.Client{Timeout: time.Minute, Transport: recorder}
	defer func() { client = oldClient }()

	job := uploadJobForServer(t, "http://upload.test", "b-deadline")
	job.Files = []string{path}

	events := captureSidecarEvents(t, func() { handleJob(job) })

	select {
	case hasDeadline := <-recorder.deadlines:
		if hasDeadline {
			t.Fatal("upload request carried a wall-clock deadline")
		}
	default:
		t.Fatalf("upload request never reached the transport; events=%+v", events)
	}
	if got := len(eventsOfType(events, "result")); got != 1 {
		t.Fatalf("result events = %d, want 1; events=%+v", got, events)
	}
}

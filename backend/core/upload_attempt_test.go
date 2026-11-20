// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"syscall"
	"testing"
)

func writeUploadFile(t *testing.T, size int) string {
	t.Helper()
	fp := filepath.Join(t.TempDir(), "photo.jpg")
	if err := os.WriteFile(fp, []byte(strings.Repeat("x", size)), 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}
	return fp
}

func uploadJob(serverURL, fp string, retries *RetryConfig) *JobRequest {
	return &JobRequest{
		ID:      "attempt",
		Service: "attempt.test",
		Files:   []string{fp},
		HttpSpec: &HttpRequestSpec{
			URL:             serverURL + "/upload",
			Method:          http.MethodPost,
			MultipartFields: map[string]MultipartField{"image": {Type: "file", Value: fp}},
			ResponseParser:  ResponseParserSpec{Type: "json", URLPath: "url", ThumbPath: "thumb"},
		},
		RetryConfig: retries,
	}
}

// A host that stores the image and then drops the connection without
// answering must not receive the image a second time.
func TestUploadIsNotRepeatedWhenResponseIsLost(t *testing.T) {
	fp := writeUploadFile(t, 4096)
	var stored int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		if atomic.AddInt32(&stored, 1) == 1 {
			conn, _, err := w.(http.Hijacker).Hijack()
			if err == nil {
				_ = conn.Close()
			}
			return
		}
		_, _ = w.Write([]byte(`{"url":"https://img.example/u","thumb":"https://img.example/t"}`))
	}))
	defer server.Close()

	_, err := ExecuteHttpUploadWithData(context.Background(), server.Client(), fp, uploadJob(server.URL, fp, fastRetries()))
	if err == nil {
		t.Fatal("expected the lost response to fail the upload")
	}
	if !strings.Contains(err.Error(), "no response from host after upload; check the host before retrying") {
		t.Fatalf("error = %q, want the no-response message", err)
	}
	if got := atomic.LoadInt32(&stored); got != 1 {
		t.Fatalf("host stored the image %d times, want 1", got)
	}
}

// A connection that fails before any of the body is sent is still retried.
func TestUploadRetriesConnectionFailureBeforeBodyIsSent(t *testing.T) {
	fp := writeUploadFile(t, 4096)
	var stored int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		atomic.AddInt32(&stored, 1)
		_, _ = w.Write([]byte(`{"url":"https://img.example/u","thumb":"https://img.example/t"}`))
	}))
	defer server.Close()

	var dials int32
	dialer := &net.Dialer{}
	client := &http.Client{Transport: &http.Transport{
		DialContext: func(ctx context.Context, network, addr string) (net.Conn, error) {
			if atomic.AddInt32(&dials, 1) == 1 {
				return nil, &net.OpError{Op: "dial", Net: network, Err: os.NewSyscallError("connect", syscall.ECONNREFUSED)}
			}
			return dialer.DialContext(ctx, network, addr)
		},
	}}

	result, err := ExecuteHttpUploadWithData(context.Background(), client, fp, uploadJob(server.URL, fp, fastRetries()))
	if err != nil {
		t.Fatalf("upload failed: %v", err)
	}
	if result.URL != "https://img.example/u" {
		t.Fatalf("result url = %q", result.URL)
	}
	if got := atomic.LoadInt32(&stored); got != 1 {
		t.Fatalf("host stored the image %d times, want 1", got)
	}
}

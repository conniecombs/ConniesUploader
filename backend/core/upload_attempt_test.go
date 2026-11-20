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
	"time"
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

func setUploadLimits(t *testing.T, stall, response time.Duration) {
	t.Helper()
	oldStall, oldResponse := UploadStallTimeout, UploadResponseTimeout
	UploadStallTimeout, UploadResponseTimeout = stall, response
	t.Cleanup(func() { UploadStallTimeout, UploadResponseTimeout = oldStall, oldResponse })
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

// slowTransport reads the request body in small steps, like a slow uplink,
// then answers. It honours request cancellation.
type slowTransport struct {
	step  time.Duration
	chunk int
}

func (s slowTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	defer req.Body.Close()
	buf := make([]byte, s.chunk)
	for {
		_, err := io.ReadFull(req.Body, buf)
		if err == io.EOF || err == io.ErrUnexpectedEOF {
			break
		}
		if err != nil {
			return nil, err
		}
		select {
		case <-time.After(s.step):
		case <-req.Context().Done():
			return nil, req.Context().Err()
		}
	}
	body := `{"url":"https://img.example/u","thumb":"https://img.example/t"}`
	return &http.Response{
		StatusCode: http.StatusOK,
		Header:     http.Header{"Content-Type": {"application/json"}},
		Body:       io.NopCloser(strings.NewReader(body)),
		Request:    req,
	}, nil
}

// An upload that keeps moving is never cut off by a wall-clock limit, even
// when it takes far longer than the client's whole-request timeout.
func TestSlowUploadIsNotCutOffByWallClockLimit(t *testing.T) {
	setUploadLimits(t, time.Second, time.Second)
	fp := writeUploadFile(t, 64*1024)
	client := &http.Client{
		Timeout:   100 * time.Millisecond,
		Transport: slowTransport{step: 10 * time.Millisecond, chunk: 1024},
	}
	start := time.Now()
	result, err := ExecuteHttpUploadWithData(context.Background(), client, fp, uploadJob("http://slow.test", fp, &RetryConfig{}))
	if err != nil {
		t.Fatalf("slow upload failed after %v: %v", time.Since(start), err)
	}
	if result.URL != "https://img.example/u" {
		t.Fatalf("result url = %q", result.URL)
	}
	if elapsed := time.Since(start); elapsed < 300*time.Millisecond {
		t.Fatalf("upload took %v; the test needs it to outlast the client timeout", elapsed)
	}
}

// stalledTransport reads a little of the body and then stops, like a dead
// uplink, until the request is cancelled.
type stalledTransport struct{}

func (stalledTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	defer req.Body.Close()
	_, _ = io.ReadFull(req.Body, make([]byte, 512))
	<-req.Context().Done()
	return nil, req.Context().Err()
}

func TestStalledUploadFailsAfterStallTimeout(t *testing.T) {
	setUploadLimits(t, 200*time.Millisecond, time.Second)
	fp := writeUploadFile(t, 64*1024)
	client := &http.Client{Transport: stalledTransport{}}

	start := time.Now()
	_, err := ExecuteHttpUploadWithData(context.Background(), client, fp, uploadJob("http://stall.test", fp, &RetryConfig{}))
	if err == nil {
		t.Fatal("expected a stalled upload to fail")
	}
	if !strings.Contains(err.Error(), "upload stalled") {
		t.Fatalf("error = %q, want an upload stalled message", err)
	}
	if elapsed := time.Since(start); elapsed > 5*time.Second {
		t.Fatalf("stall detected after %v, want about 200ms", elapsed)
	}
	if !IsRetryableError(err, 0, GetDefaultRetryConfig()) {
		t.Fatal("a stall before the body was sent should stay retryable")
	}
}

// The last body bytes can still sit in OS buffers on a slow uplink when the
// transport finishes writing, so the transport's short response-header
// timeout must not cut the upload's own response wait short.
func TestUploadResponseWaitIgnoresTransportHeaderTimeout(t *testing.T) {
	setUploadLimits(t, time.Second, 5*time.Second)
	fp := writeUploadFile(t, 4096)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		time.Sleep(400 * time.Millisecond)
		_, _ = w.Write([]byte(`{"url":"https://img.example/u","thumb":"https://img.example/t"}`))
	}))
	defer server.Close()

	transport := &http.Transport{ResponseHeaderTimeout: 100 * time.Millisecond}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport}
	result, err := ExecuteHttpUploadWithData(context.Background(), client, fp, uploadJob(server.URL, fp, &RetryConfig{}))
	if err != nil {
		t.Fatalf("upload failed: %v", err)
	}
	if result.URL != "https://img.example/u" {
		t.Fatalf("result url = %q", result.URL)
	}
	if transport.ResponseHeaderTimeout != 100*time.Millisecond {
		t.Fatal("the shared transport's settings were changed")
	}
}

// After the body is sent the wait for the host's answer is bounded, and the
// upload is not sent again.
func TestUploadResponseWaitIsBoundedAndNotRetried(t *testing.T) {
	setUploadLimits(t, time.Second, 200*time.Millisecond)
	fp := writeUploadFile(t, 4096)
	release := make(chan struct{})
	var stored int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		atomic.AddInt32(&stored, 1)
		select {
		case <-release:
		case <-r.Context().Done():
		}
	}))
	defer server.Close()
	defer close(release)

	start := time.Now()
	_, err := ExecuteHttpUploadWithData(context.Background(), server.Client(), fp, uploadJob(server.URL, fp, fastRetries()))
	if err == nil {
		t.Fatal("expected the silent host to fail the upload")
	}
	if !strings.Contains(err.Error(), "no response from host") || !strings.Contains(err.Error(), "check the host before retrying") {
		t.Fatalf("error = %q, want the no-response message", err)
	}
	if elapsed := time.Since(start); elapsed > 5*time.Second {
		t.Fatalf("gave up after %v, want about 200ms", elapsed)
	}
	if got := atomic.LoadInt32(&stored); got != 1 {
		t.Fatalf("host received the upload %d times, want 1", got)
	}
}

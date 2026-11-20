// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"sync/atomic"
	"syscall"
	"testing"
	"time"
)

// fastRetries retries quickly so a test that wrongly retries still finishes.
func fastRetries() *RetryConfig {
	return &RetryConfig{
		MaxRetries:         3,
		InitialBackoff:     time.Millisecond,
		MaxBackoff:         time.Millisecond,
		BackoffMultiplier:  1,
		RetryableHTTPCodes: GetDefaultRetryConfig().RetryableHTTPCodes,
	}
}

func TestIsRetryableErrorNeverReadsResponseText(t *testing.T) {
	config := GetDefaultRetryConfig()
	page := "<script>if (typeof x === 'undefined') { setTimeout(f, 5) }</script> EOF timeout connection reset"
	cases := []struct {
		name   string
		err    error
		status int
	}{
		{"status error with script body", &HTTPStatusError{StatusCode: 403, Body: page}, 403},
		{"follow-up 404 after a 200 upload", fmt.Errorf("wrapped: %w", &HTTPStatusError{Context: "response follow-up", StatusCode: 404, Body: page}), 200},
		{"plain text that only looks transient", errors.New(page), 0},
		{"parse error after a 200 response", errors.New("unexpected EOF in body: " + page), 200},
	}
	for _, tc := range cases {
		if IsRetryableError(tc.err, tc.status, config) {
			t.Errorf("%s: retryable, want not retryable", tc.name)
		}
	}
}

func TestIsRetryableErrorUsesStatusCodes(t *testing.T) {
	config := GetDefaultRetryConfig()
	if !IsRetryableError(&HTTPStatusError{StatusCode: 503}, 503, config) {
		t.Error("503 with status code: want retryable")
	}
	if !IsRetryableError(&HTTPStatusError{StatusCode: 429}, 0, config) {
		t.Error("typed 429 without a separate status code: want retryable")
	}
	if IsRetryableError(&HTTPStatusError{StatusCode: 404}, 0, config) {
		t.Error("typed 404: want not retryable")
	}
}

type timeoutErr struct{}

func (timeoutErr) Error() string   { return "deadline" }
func (timeoutErr) Timeout() bool   { return true }
func (timeoutErr) Temporary() bool { return true }

func TestIsRetryableErrorClassifiesTransportErrorsByType(t *testing.T) {
	config := GetDefaultRetryConfig()
	retryable := map[string]error{
		"EOF":            &url.Error{Op: "Post", URL: "http://h/u", Err: io.EOF},
		"unexpected EOF": fmt.Errorf("read: %w", io.ErrUnexpectedEOF),
		"timeout":        &url.Error{Op: "Post", URL: "http://h/u", Err: timeoutErr{}},
		"reset":          &net.OpError{Op: "read", Net: "tcp", Err: os.NewSyscallError("read", syscall.ECONNRESET)},
		"dial":           &net.OpError{Op: "dial", Net: "tcp", Err: errors.New("anything")},
		"dns":            &net.DNSError{Err: "no such host", Name: "x.invalid", IsNotFound: true},
		"bare errno":     syscall.ECONNREFUSED,
	}
	for name, err := range retryable {
		if !IsRetryableError(err, 0, config) {
			t.Errorf("%s: not retryable, want retryable", name)
		}
	}
	notRetryable := map[string]error{
		"cancel":       &url.Error{Op: "Post", URL: "http://h/u", Err: context.Canceled},
		"file missing": &url.Error{Op: "Post", URL: "http://h/u", Err: os.ErrNotExist},
		"plain":        errors.New("i/o timeout while reading eof"),
	}
	for name, err := range notRetryable {
		if IsRetryableError(err, 0, config) {
			t.Errorf("%s: retryable, want not retryable", name)
		}
	}
}

func TestExtractStatusCodeUsesTypedError(t *testing.T) {
	if got := ExtractStatusCode(fmt.Errorf("x: %w", &HTTPStatusError{StatusCode: 502})); got != 502 {
		t.Fatalf("ExtractStatusCode = %d, want 502", got)
	}
	if got := ExtractStatusCode(errors.New("page says status code 503 and HTTP 500")); got != 0 {
		t.Fatalf("ExtractStatusCode read text: got %d, want 0", got)
	}
}

func TestGenericRequestIsNotRetriedForScriptInErrorPage(t *testing.T) {
	var hits int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&hits, 1)
		w.WriteHeader(http.StatusForbidden)
		_, _ = w.Write([]byte("<html><script>setTimeout(function(){}, 5); if (typeof jQuery) {}</script>Forbidden</html>"))
	}))
	defer server.Close()

	spec := &GenericHttpRequestSpec{URL: server.URL + "/galleries", Method: http.MethodPost,
		FormFields: map[string]string{"gallery_name": "Set 1"}}
	_, err := ExecuteGenericRequest(context.Background(), server.Client(), spec, &JobRequest{RetryConfig: fastRetries()})
	if err == nil {
		t.Fatal("expected an error for HTTP 403")
	}
	var statusErr *HTTPStatusError
	if !errors.As(err, &statusErr) || statusErr.StatusCode != http.StatusForbidden {
		t.Fatalf("error %v is not an HTTP 403 status error", err)
	}
	if got := atomic.LoadInt32(&hits); got != 1 {
		t.Fatalf("host received %d requests, want 1", got)
	}
}

func TestGenericRequestRetriesDroppedConnection(t *testing.T) {
	var hits int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if atomic.AddInt32(&hits, 1) == 1 {
			conn, _, err := w.(http.Hijacker).Hijack()
			if err == nil {
				_ = conn.Close()
			}
			return
		}
		_, _ = w.Write([]byte("ok"))
	}))
	defer server.Close()

	spec := &GenericHttpRequestSpec{URL: server.URL + "/post", Method: http.MethodPost,
		FormFields: map[string]string{"a": "b"}}
	if _, err := ExecuteGenericRequest(context.Background(), server.Client(), spec, &JobRequest{RetryConfig: fastRetries()}); err != nil {
		t.Fatalf("ExecuteGenericRequest returned error: %v", err)
	}
	if got := atomic.LoadInt32(&hits); got != 2 {
		t.Fatalf("host received %d requests, want 2 (one retry)", got)
	}
}

func TestUploadIsNotRepeatedWhenResponseFollowUpReturnsScriptPage(t *testing.T) {
	fp := filepath.Join(t.TempDir(), "a.jpg")
	if err := os.WriteFile(fp, []byte("jpeg-bytes"), 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}
	var uploads int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/upload":
			atomic.AddInt32(&uploads, 1)
			_, _ = io.Copy(io.Discard, r.Body)
			_, _ = w.Write([]byte("<textarea name='fn'>abc</textarea>"))
		default:
			w.WriteHeader(http.StatusNotFound)
			_, _ = w.Write([]byte("<script>if (typeof x === 'undefined') {}</script>Not found"))
		}
	}))
	defer server.Close()

	job := &JobRequest{
		ID:      "followup",
		Service: "followup.test",
		Files:   []string{fp},
		HttpSpec: &HttpRequestSpec{
			URL:             server.URL + "/upload",
			Method:          http.MethodPost,
			MultipartFields: map[string]MultipartField{"file": {Type: "file", Value: fp}},
			ResponseParser: ResponseParserSpec{
				Type: "html",
				FollowUpRequest: &ResponseFollowUpSpec{
					URL:           server.URL + "/result",
					ResponseType:  "html",
					ExtractFields: map[string]string{"fn": "textarea[name='fn']"},
					FormFields:    map[string]string{"fn": "{fn}"},
				},
				URLPath: "regex:(https?://\\S+)",
			},
		},
		RetryConfig: fastRetries(),
	}
	if _, err := ExecuteHttpUploadWithData(context.Background(), server.Client(), fp, job); err == nil {
		t.Fatal("expected the follow-up 404 to fail the upload")
	}
	if got := atomic.LoadInt32(&uploads); got != 1 {
		t.Fatalf("file uploaded %d times, want 1", got)
	}
}

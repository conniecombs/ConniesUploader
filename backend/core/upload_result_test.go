// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func writeUploadTestFile(t *testing.T, dir, name string, size int) string {
	t.Helper()
	path := filepath.Join(dir, name)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	data := make([]byte, size)
	copy(data, []byte{0xff, 0xd8, 0xff, 0xe0})
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatalf("write %s: %v", name, err)
	}
	return path
}

func fastRetryConfig() *RetryConfig {
	return &RetryConfig{
		MaxRetries:         2,
		InitialBackoff:     time.Millisecond,
		MaxBackoff:         time.Millisecond,
		BackoffMultiplier:  1,
		RetryableHTTPCodes: []int{408, 429, 500, 502, 503, 504},
	}
}

func jsonUploadJob(serverURL, fp string, parser ResponseParserSpec) *JobRequest {
	return &JobRequest{
		Action:      "http_upload",
		Service:     "example.test",
		Files:       []string{fp},
		RetryConfig: fastRetryConfig(),
		HttpSpec: &HttpRequestSpec{
			URL:    serverURL + "/upload",
			Method: http.MethodPost,
			MultipartFields: map[string]MultipartField{
				"img": {Type: "file", Value: fp},
			},
			ResponseParser: parser,
		},
	}
}

func TestExecuteHttpUploadRejectedStatusFailsWithHostMessage(t *testing.T) {
	fp := writeUploadTestFile(t, t.TempDir(), "a.jpg", 64)
	cases := []struct {
		name     string
		status   int
		body     string
		wantText []string
	}{
		{"json error field", http.StatusBadRequest, `{"error":"image too large"}`, []string{"HTTP 400", "image too large"}},
		{"json message field", http.StatusUnprocessableEntity, `{"message":"File type not allowed","errors":{}}`, []string{"HTTP 422", "File type not allowed"}},
		{"nested error object", http.StatusForbidden, `{"error":{"code":7,"message":"quota exceeded"}}`, []string{"HTTP 403", "quota exceeded"}},
		{"html page", http.StatusNotFound, `<html><head><title>x</title><script>var a = 1;</script></head><body><h1>Not   Found</h1></body></html>`, []string{"HTTP 404", "Not Found"}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var hits int32
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				atomic.AddInt32(&hits, 1)
				_, _ = io.Copy(io.Discard, r.Body)
				w.WriteHeader(tc.status)
				_, _ = w.Write([]byte(tc.body))
			}))
			defer server.Close()

			job := jsonUploadJob(server.URL, fp, ResponseParserSpec{Type: "json", URLPath: "show_url", ThumbPath: "th_url"})
			result, err := ExecuteHttpUploadWithData(context.Background(), server.Client(), fp, job)
			if err == nil {
				t.Fatalf("rejected upload succeeded: %+v", result)
			}
			for _, want := range tc.wantText {
				if !strings.Contains(err.Error(), want) {
					t.Fatalf("error %q does not mention %q", err, want)
				}
			}
			if strings.Contains(err.Error(), "var a") {
				t.Fatalf("error leaks script text: %q", err)
			}
			if got := atomic.LoadInt32(&hits); got != 1 {
				t.Fatalf("upload attempts = %d, want 1 (a rejection must not be re-sent)", got)
			}
		})
	}
}

func TestExecuteHttpUploadWithoutViewerLinkFails(t *testing.T) {
	fp := writeUploadTestFile(t, t.TempDir(), "a.jpg", 64)
	cases := []struct {
		name     string
		body     string
		parser   ResponseParserSpec
		wantText string
	}{
		{"empty json url", `{"show_url":"","th_url":""}`, ResponseParserSpec{Type: "json", URLPath: "show_url", ThumbPath: "th_url"}, "no image link"},
		{"json error on 200", `{"error":"daily limit reached"}`, ResponseParserSpec{Type: "json", URLPath: "show_url"}, "daily limit reached"},
		{"html without link", `<html><body><b>Upload failed: File type not allowed</b></body></html>`, ResponseParserSpec{Type: "html", URLPath: `regex:\[URL=(https?://[^\]]+)\]`}, "Upload failed: File type not allowed"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var hits int32
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				atomic.AddInt32(&hits, 1)
				_, _ = io.Copy(io.Discard, r.Body)
				_, _ = w.Write([]byte(tc.body))
			}))
			defer server.Close()

			job := jsonUploadJob(server.URL, fp, tc.parser)
			result, err := ExecuteHttpUploadWithData(context.Background(), server.Client(), fp, job)
			if err == nil {
				t.Fatalf("upload without a viewer link succeeded: %+v", result)
			}
			if !strings.Contains(err.Error(), tc.wantText) {
				t.Fatalf("error %q does not mention %q", err, tc.wantText)
			}
			if got := atomic.LoadInt32(&hits); got != 1 {
				t.Fatalf("upload attempts = %d, want 1", got)
			}
		})
	}
}

func TestExecuteHttpUploadStatusCheckFailureCarriesHostMessage(t *testing.T) {
	fp := writeUploadTestFile(t, t.TempDir(), "a.jpg", 64)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		_, _ = w.Write([]byte(`{"success":false,"status":400,"data":{"error":"File is over the size limit"}}`))
	}))
	defer server.Close()

	job := jsonUploadJob(server.URL, fp, ResponseParserSpec{
		Type: "json", URLPath: "data.link", StatusPath: "success", SuccessValue: "true",
	})
	_, err := ExecuteHttpUploadWithData(context.Background(), server.Client(), fp, job)
	if err == nil || !strings.Contains(err.Error(), "File is over the size limit") {
		t.Fatalf("err = %v, want the host's error message", err)
	}
}

func TestUploadErrorSnippetRedactsCredentials(t *testing.T) {
	fp := writeUploadTestFile(t, t.TempDir(), "a.jpg", 64)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		w.WriteHeader(http.StatusUnauthorized)
		_, _ = w.Write([]byte(`Bad key s3cr3t-api-key for user`))
	}))
	defer server.Close()

	job := jsonUploadJob(server.URL, fp, ResponseParserSpec{Type: "json", URLPath: "url"})
	job.Creds = map[string]string{"api_key": "s3cr3t-api-key"}
	_, err := ExecuteHttpUploadWithData(context.Background(), server.Client(), fp, job)
	if err == nil {
		t.Fatal("rejected upload succeeded")
	}
	if strings.Contains(err.Error(), "s3cr3t-api-key") {
		t.Fatalf("error leaks a credential: %q", err)
	}
	if !strings.Contains(err.Error(), "HTTP 401") {
		t.Fatalf("error %q does not mention the status", err)
	}
}

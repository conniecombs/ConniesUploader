// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestProcessFileGenericReportsUploadWithoutLinkAsFailed(t *testing.T) {
	imagePath := t.TempDir() + "/a.jpg"
	if err := createTestImage(imagePath); err != nil {
		t.Fatalf("create test image: %v", err)
	}
	cases := []struct {
		name   string
		status int
		body   string
	}{
		{"rejected with json error", http.StatusBadRequest, `{"error":"image too large"}`},
		{"accepted without link", http.StatusOK, `{"show_url":"","th_url":""}`},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				_, _ = io.Copy(io.Discard, r.Body)
				w.WriteHeader(tc.status)
				_, _ = w.Write([]byte(tc.body))
			}))
			defer server.Close()

			oldClient := client
			client = server.Client()
			defer func() { client = oldClient }()

			job := &JobRequest{
				ID:      "job-1",
				Action:  "http_upload",
				Service: "example.test",
				Files:   []string{imagePath},
				RetryConfig: &RetryConfig{
					MaxRetries:         1,
					InitialBackoff:     time.Millisecond,
					MaxBackoff:         time.Millisecond,
					BackoffMultiplier:  1,
					RetryableHTTPCodes: []int{429, 503},
				},
				HttpSpec: &HttpRequestSpec{
					URL:    server.URL + "/upload",
					Method: http.MethodPost,
					MultipartFields: map[string]MultipartField{
						"img": {Type: "file", Value: imagePath},
					},
					ResponseParser: ResponseParserSpec{Type: "json", URLPath: "show_url", ThumbPath: "th_url"},
				},
			}

			events := captureSidecarEvents(t, func() { processFileGeneric(imagePath, job) })

			if results := eventsOfType(events, "result"); len(results) != 0 {
				t.Fatalf("got result events for a failed upload: %+v", results)
			}
			var failed, done bool
			for _, event := range eventsOfType(events, "status") {
				failed = failed || event.Status == "Failed"
				done = done || event.Status == "Done"
			}
			if !failed || done {
				t.Fatalf("status events failed=%v done=%v, want Failed only", failed, done)
			}
			errs := eventsOfType(events, "error")
			if len(errs) != 1 || strings.TrimSpace(errs[0].Msg) == "" || errs[0].FilePath != imagePath {
				t.Fatalf("error events = %+v, want one per-file error with a reason", errs)
			}
		})
	}
}

// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package main

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestUploadJobSkipsInvalidFileAndUploadsTheRest(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":"success","data":{"image_url":"https://img.test/u","thumbnail_url":"https://img.test/t"}}`))
	}))
	defer server.Close()

	oldClient := client
	client = server.Client()
	defer func() { client = oldClient }()

	good := filepath.Join(t.TempDir(), "good.jpg")
	if err := os.WriteFile(good, []byte("jpeg-bytes"), 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}
	bad := "/nonexistent/bad.jpg"

	job := JobRequest{
		ID:      "job-validate",
		Action:  "http_upload",
		Service: "example.host",
		Files:   []string{good, bad},
		Config:  map[string]string{"threads": "1"},
		HttpSpec: &HttpRequestSpec{
			URL:    server.URL + "/upload",
			Method: http.MethodPost,
			MultipartFields: map[string]MultipartField{
				"image": {Type: "file", Value: ""},
			},
			ResponseParser: ResponseParserSpec{
				Type: "json", URLPath: "data.image_url", ThumbPath: "data.thumbnail_url",
				StatusPath: "status", SuccessValue: "success",
			},
		},
	}

	events := captureSidecarEvents(t, func() { handleJob(job) })

	results := eventsOfType(events, "result")
	if len(results) != 1 || results[0].FilePath != good || results[0].Url != "https://img.test/u" {
		t.Fatalf("results = %+v, want one result for %s", results, good)
	}

	var badFailed, badError bool
	for _, event := range events {
		if event.FilePath != bad {
			continue
		}
		if event.Type == "status" && event.Status == "Failed" {
			badFailed = true
		}
		if event.Type == "error" && strings.Contains(event.Msg, "Invalid file") {
			badError = true
		}
	}
	if !badFailed || !badError {
		t.Fatalf("bad file did not get Failed status and error event; events=%+v", events)
	}
	if got := len(eventsOfType(events, "batch_complete")); got != 1 {
		t.Fatalf("batch_complete count = %d, want 1", got)
	}
}

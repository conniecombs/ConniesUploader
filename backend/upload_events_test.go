// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package main

import (
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/conniecombs/GolangVersion/core"
)

func TestUploadOrderJobUploadsOneFileAtATime(t *testing.T) {
	dir := t.TempDir()
	var files []string
	for _, name := range []string{"cover.jpg", "a.jpg", "b.jpg", "c.jpg"} {
		fp := dir + "/" + name
		if err := createTestImage(fp); err != nil {
			t.Fatalf("create test image: %v", err)
		}
		files = append(files, fp)
	}

	var mu sync.Mutex
	active, maxActive := 0, 0
	var order []string // uploaded file names, in arrival order
	var baseURL string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/upload":
			mu.Lock()
			active++
			if active > maxActive {
				maxActive = active
			}
			mu.Unlock()
			_, header, err := r.FormFile("files[0]")
			time.Sleep(20 * time.Millisecond)
			mu.Lock()
			active--
			if err == nil {
				order = append(order, header.Filename)
			}
			mu.Unlock()
			_, _ = w.Write([]byte(`{"success":"` + baseURL + `/complete"}`))
		case "/complete":
			mu.Lock()
			var b strings.Builder
			for i := range order {
				fmt.Fprintf(&b, "[URL=https://img.example/view/ID%d][IMG]https://thumbs.example/ID%d_t.jpg[/IMG][/URL]", i, i)
			}
			mu.Unlock()
			_, _ = w.Write([]byte(b.String()))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	baseURL = server.URL

	oldClient := client
	client = server.Client()
	defer func() { client = oldClient }()

	job := JobRequest{
		ID:      "job-order",
		Action:  "http_upload",
		Service: "upload-order.test",
		Files:   files,
		Config:  map[string]string{"threads": "3"},
		HttpSpec: &HttpRequestSpec{
			URL:    server.URL + "/upload",
			Method: http.MethodPost,
			MultipartFields: map[string]MultipartField{
				"files[0]": {Type: "file", Value: files[0]},
			},
			ResponseParser: ResponseParserSpec{Type: "json", URLPath: "success"},
		},
		ResolveSpec: &core.BatchResolveSpec{
			ResultURL:     "{url}",
			PollDelaysMs:  []int{5},
			LinkExtractor: `\[URL=(?P<image_url>https://img\.example/view/[^\]]+)\]\[IMG\](?P<thumb_url>[^\[]+)\[/IMG\]\[/URL\]`,
			FileMatchMode: "upload_order",
		},
	}

	events := captureSidecarEvents(t, func() { processUploadFiles(job, processFileGenericCtx) })

	if maxActive != 1 {
		t.Fatalf("max concurrent uploads = %d, want 1 for an upload_order job", maxActive)
	}
	links := make(map[string]string)
	for _, event := range eventsOfType(events, "result") {
		links[filepath.Base(event.FilePath)] = event.Url
	}
	for i, name := range order {
		if want := fmt.Sprintf("https://img.example/view/ID%d", i); links[name] != want {
			t.Fatalf("%s (upload #%d) got %q, want %q (all: %v)", name, i+1, links[name], want, links)
		}
	}
	if len(links) != len(files) {
		t.Fatalf("results = %v, want one per file", links)
	}
}

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

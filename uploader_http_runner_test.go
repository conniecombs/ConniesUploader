// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/conniecombs/GolangVersion/core"
)

func TestExecuteHttpUploadSupportsChainedPreRequests(t *testing.T) {
	tmpDir := t.TempDir()
	imagePath := tmpDir + "/upload.jpg"
	if err := createTestImage(imagePath); err != nil {
		t.Fatalf("Failed to create test image: %v", err)
	}

	var baseURL string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/login":
			http.SetCookie(w, &http.Cookie{Name: "session", Value: "cookie-ok"})
			_, _ = w.Write([]byte(`<input name="_token" value="csrf-123">`))
		case "/session":
			if got := r.Header.Get("X-CSRF-TOKEN"); got != "csrf-123" {
				t.Fatalf("X-CSRF-TOKEN = %q, want csrf-123", got)
			}
			if got := r.FormValue("_token"); got != "csrf-123" {
				t.Fatalf("_token = %q, want csrf-123", got)
			}
			if cookie, err := r.Cookie("session"); err != nil || cookie.Value != "cookie-ok" {
				t.Fatalf("session cookie missing after first pre-request: %v", err)
			}
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"upload_token":"upload-456","endpoint":"/upload"}`))
		case "/upload":
			if got := r.URL.Query().Get("upload_id"); got != "abc" {
				t.Fatalf("upload_id = %q, want abc", got)
			}
			if got := r.Header.Get("X-Upload-Token"); got != "upload-456" {
				t.Fatalf("X-Upload-Token = %q, want upload-456", got)
			}
			if err := r.ParseMultipartForm(10 << 20); err != nil {
				t.Fatalf("ParseMultipartForm failed: %v", err)
			}
			if got := r.FormValue("session"); got != "upload-456" {
				t.Fatalf("session field = %q, want upload-456", got)
			}
			if _, _, err := r.FormFile("image"); err != nil {
				t.Fatalf("image file missing: %v", err)
			}
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"success":true,"files":[{"sourceUrl":"https://cdn.example/source.jpg","thumbUrl":"https://cdn.example/thumb.jpg"}]}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	baseURL = server.URL

	oldClient := client
	client = server.Client()
	defer func() { client = oldClient }()

	job := &JobRequest{
		Action:  "http_upload",
		Service: "test.service",
		Files:   []string{imagePath},
		Creds:   map[string]string{},
		Config:  map[string]string{"user_agent": "test-agent"},
		HttpSpec: &HttpRequestSpec{
			URL:    baseURL + "/fallback?upload_id=abc",
			Method: "POST",
			Headers: map[string]string{
				"X-Upload-Token": "{upload_token}",
			},
			PreRequest: &PreRequestSpec{
				Action:       "get_csrf",
				URL:          baseURL + "/login",
				Method:       "GET",
				UseCookies:   true,
				ResponseType: "html",
				ExtractFields: map[string]string{
					"csrf": "input[name='_token']",
				},
				FollowUpRequest: &PreRequestSpec{
					Action:       "get_upload_session",
					URL:          baseURL + "/session",
					Method:       "POST",
					UseCookies:   true,
					ResponseType: "json",
					Headers: map[string]string{
						"X-CSRF-TOKEN": "{csrf}",
					},
					FormFields: map[string]string{
						"_token": "{csrf}",
					},
					ExtractFields: map[string]string{
						"upload_token": "upload_token",
						"endpoint":     "endpoint",
					},
				},
			},
			MultipartFields: map[string]MultipartField{
				"image":   {Type: "file", Value: imagePath},
				"session": {Type: "dynamic", Value: "upload_token"},
			},
			ResponseParser: ResponseParserSpec{
				Type:         "json",
				StatusPath:   "success",
				SuccessValue: "true",
				URLPath:      "files.0.sourceUrl",
				ThumbPath:    "files.0.thumbUrl",
			},
		},
	}

	urlStr, thumbStr, err := executeHttpUpload(context.Background(), imagePath, job)
	if err != nil {
		t.Fatalf("executeHttpUpload failed: %v", err)
	}
	if urlStr != "https://cdn.example/source.jpg" {
		t.Fatalf("url = %q", urlStr)
	}
	if thumbStr != "https://cdn.example/thumb.jpg" {
		t.Fatalf("thumb = %q", thumbStr)
	}
}

func TestExecuteHttpUploadClosesPipeReaderWhenRequestCreationFails(t *testing.T) {
	tmpDir := t.TempDir()
	imagePath := tmpDir + "/upload.jpg"
	if err := createTestImage(imagePath); err != nil {
		t.Fatalf("Failed to create test image: %v", err)
	}

	before := runtime.NumGoroutine()
	job := &JobRequest{
		Action:  "http_upload",
		Service: "test.service",
		Files:   []string{imagePath},
		HttpSpec: &HttpRequestSpec{
			URL:    "://bad-url",
			Method: "POST",
			MultipartFields: map[string]MultipartField{
				"image": {Type: "file", Value: imagePath},
			},
			ResponseParser: ResponseParserSpec{Type: "json"},
		},
	}

	for i := 0; i < 20; i++ {
		if _, _, err := core.ExecuteHttpUpload(context.Background(), http.DefaultClient, imagePath, job); err == nil {
			t.Fatal("ExecuteHttpUpload succeeded with an invalid URL")
		}
	}

	deadline := time.Now().Add(1 * time.Second)
	for time.Now().Before(deadline) {
		runtime.GC()
		if runtime.NumGoroutine() <= before+4 {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("multipart pipe writer goroutines appear leaked: before=%d after=%d", before, runtime.NumGoroutine())
}

func TestParseHttpResponseSupportsHTMLAndTemplates(t *testing.T) {
	resp := &http.Response{
		Body: io.NopCloser(strings.NewReader(`<input name="link_url" value="https://vipr.im/i/a.jpg"><input name="thumb_url" value="https://vipr.im/th/a.jpg">`)),
	}

	urlStr, thumbStr, err := core.ParseHttpResponse(resp, &core.ResponseParserSpec{
		Type:      "html",
		URLPath:   "input[name='link_url']",
		ThumbPath: "input[name='thumb_url']",
	}, "upload.jpg")
	if err != nil {
		t.Fatalf("ParseHttpResponse failed: %v", err)
	}
	if urlStr != "https://vipr.im/i/a.jpg" || thumbStr != "https://vipr.im/th/a.jpg" {
		t.Fatalf("unexpected parsed urls: %q %q", urlStr, thumbStr)
	}
}

func TestGetJSONValueSupportsArrayIndexes(t *testing.T) {
	data := map[string]interface{}{
		"files": []interface{}{
			map[string]interface{}{
				"sourceUrl": "https://cdn.example/source.jpg",
			},
		},
	}

	if got := getJSONValue(data, "files.0.sourceUrl"); got != "https://cdn.example/source.jpg" {
		t.Fatalf("getJSONValue array path = %q", got)
	}
	if got := getJSONValue(data, "files.1.sourceUrl"); got != "" {
		t.Fatalf("out-of-range array path = %q, want empty", got)
	}
}

func TestSendJobEventEchoesRequestID(t *testing.T) {
	job := &JobRequest{ID: "request-123"}

	oldStdout := os.Stdout
	reader, writer, err := os.Pipe()
	if err != nil {
		t.Fatalf("os.Pipe failed: %v", err)
	}
	os.Stdout = writer
	sendJobEvent(job, OutputEvent{Type: "result", Status: "success"})
	_ = writer.Close()
	os.Stdout = oldStdout

	raw, err := io.ReadAll(reader)
	if err != nil {
		t.Fatalf("ReadAll failed: %v", err)
	}

	var decoded OutputEvent
	if err := json.Unmarshal([]byte(strings.TrimSpace(string(raw))), &decoded); err != nil {
		t.Fatalf("Unmarshal emitted event failed: %v; raw=%q", err, raw)
	}
	if decoded.ID != job.ID {
		t.Fatalf("event id = %q, want %q", decoded.ID, job.ID)
	}
}

func TestResponseTemplateUsesJSONAndFilePlaceholders(t *testing.T) {
	resp := &http.Response{
		Body: io.NopCloser(strings.NewReader(`{"success":true,"id":"abc123"}`)),
	}
	urlStr, _, err := core.ParseHttpResponse(resp, &core.ResponseParserSpec{
		Type:         "json",
		StatusPath:   "success",
		SuccessValue: "true",
		URLTemplate:  "https://example.com/p/{id}/{filename}",
	}, "my image.jpg")
	if err != nil {
		t.Fatalf("ParseHttpResponse failed: %v", err)
	}
	if urlStr != "https://example.com/p/abc123/my image.jpg" {
		t.Fatalf("template result = %q", urlStr)
	}
}

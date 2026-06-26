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
	"sync/atomic"
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

func TestProcessFileGenericUsesSingleJobRetryPolicy(t *testing.T) {
	tmpDir := t.TempDir()
	imagePath := tmpDir + "/upload.jpg"
	if err := createTestImage(imagePath); err != nil {
		t.Fatalf("Failed to create test image: %v", err)
	}

	var attempts int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&attempts, 1)
		_, _ = io.Copy(io.Discard, r.Body)
		w.WriteHeader(http.StatusTooManyRequests)
		_, _ = w.Write([]byte(`{"success":false}`))
	}))
	defer server.Close()

	oldClient := client
	client = server.Client()
	defer func() { client = oldClient }()

	job := &JobRequest{
		Action:  "http_upload",
		Service: "retry-policy.test",
		Files:   []string{imagePath},
		RetryConfig: &RetryConfig{
			MaxRetries:         1,
			InitialBackoff:     time.Millisecond,
			MaxBackoff:         time.Millisecond,
			BackoffMultiplier:  1,
			RetryableHTTPCodes: []int{http.StatusTooManyRequests},
		},
		HttpSpec: &HttpRequestSpec{
			URL:    server.URL + "/upload",
			Method: "POST",
			MultipartFields: map[string]MultipartField{
				"image": {Type: "file", Value: imagePath},
			},
			ResponseParser: ResponseParserSpec{Type: "json"},
		},
	}

	processFileGeneric(imagePath, job)

	if got := atomic.LoadInt32(&attempts); got != 2 {
		t.Fatalf("upload attempts = %d, want 2 from one MaxRetries=1 policy", got)
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

func TestExecuteHttpUploadFollowsViprUploadResultForm(t *testing.T) {
	tmpDir := t.TempDir()
	imagePath := tmpDir + "/vipr-upload.jpg"
	if err := createTestImage(imagePath); err != nil {
		t.Fatalf("Failed to create test image: %v", err)
	}

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/upload":
			if err := r.ParseMultipartForm(10 << 20); err != nil {
				t.Fatalf("ParseMultipartForm failed: %v", err)
			}
			if _, _, err := r.FormFile("file_0"); err != nil {
				t.Fatalf("file_0 missing: %v", err)
			}
			_, _ = w.Write([]byte(`<HTML><BODY><Form name='F1' action='/result' target='_parent' method='POST'>
				<textarea name='fn'>abc123</textarea>
				<textarea name='st'>OK</textarea>
				<textarea name='op'>upload_result</textarea>
				<textarea name='per_row'>750</textarea>
				</Form></BODY></HTML>`))
		case "/result":
			if err := r.ParseForm(); err != nil {
				t.Fatalf("ParseForm failed: %v", err)
			}
			if got := r.FormValue("fn"); got != "abc123" {
				t.Fatalf("fn = %q, want abc123", got)
			}
			if got := r.FormValue("op"); got != "upload_result" {
				t.Fatalf("op = %q, want upload_result", got)
			}
			_, _ = w.Write([]byte(`<textarea id="tl1">[URL=https://vipr.im/abc123][IMG]https://i6.vipr.im/th/123/abc123.jpg[/IMG][/URL]</textarea>`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	job := &JobRequest{
		Action:  "http_upload",
		Service: "vipr.im",
		Files:   []string{imagePath},
		Config:  map[string]string{"threads": "1"},
		Creds:   map[string]string{},
		HttpSpec: &HttpRequestSpec{
			URL:    server.URL + "/upload",
			Method: "POST",
			MultipartFields: map[string]MultipartField{
				"file_0": {Type: "file", Value: imagePath},
			},
			ResponseParser: ResponseParserSpec{
				Type: "html",
				FollowUpRequest: &core.ResponseFollowUpSpec{
					URL:          server.URL + "/result",
					Method:       "POST",
					ResponseType: "html",
					ExtractFields: map[string]string{
						"fn":      "textarea[name='fn']",
						"st":      "textarea[name='st']",
						"op":      "textarea[name='op']",
						"per_row": "textarea[name='per_row']",
					},
					FormFields: map[string]string{
						"fn":      "{fn}",
						"st":      "{st}",
						"op":      "{op}",
						"per_row": "{per_row}",
					},
				},
				URLPath:   `regex:(?is)\[URL=(https?://vipr\.im/[^\]\s]+)\]\s*\[IMG\]`,
				ThumbPath: `regex:(?is)\[IMG\](https?://[^\[]+?)\[/IMG\]`,
			},
		},
	}

	result, err := core.ExecuteHttpUploadWithData(context.Background(), server.Client(), imagePath, job)
	if err != nil {
		t.Fatalf("ExecuteHttpUploadWithData failed: %v", err)
	}
	if result.URL != "https://vipr.im/abc123" {
		t.Fatalf("url = %q", result.URL)
	}
	if result.Thumb != "https://i6.vipr.im/th/123/abc123.jpg" {
		t.Fatalf("thumb = %q", result.Thumb)
	}
}

func TestExecuteHttpUploadResolvesTurboResultPageThumbnail(t *testing.T) {
	tmpDir := t.TempDir()
	imagePath := tmpDir + "/turbo-upload.jpg"
	if err := createTestImage(imagePath); err != nil {
		t.Fatalf("Failed to create test image: %v", err)
	}

	var baseURL string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/upload":
			if err := r.ParseMultipartForm(10 << 20); err != nil {
				t.Fatalf("ParseMultipartForm failed: %v", err)
			}
			if _, _, err := r.FormFile("qqfile"); err != nil {
				t.Fatalf("qqfile missing: %v", err)
			}
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"success":true,"newUrl":"` + baseURL + `/result"}`))
		case "/result":
			_, _ = w.Write([]byte(`<input id="imgCodeGG" value="https://www.turboimagehost.com/album/394761/miscellaneous">
			<textarea id="imgCodeURF">
				[URL=https://www.turboimagehost.com/p/123/other.jpg.html][IMG]https://s8d8.turboimg.net/t1/123_other.jpg[/IMG][/URL]
				[URL=https://www.turboimagehost.com/p/124/turbo-upload.jpg.html][IMG]https://s8d8.turboimg.net/t1/124_turbo-upload.jpg[/IMG][/URL]
			</textarea>`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	baseURL = server.URL

	job := &JobRequest{
		Action:  "http_upload",
		Service: "turboimagehost",
		Files:   []string{imagePath},
		Config:  map[string]string{},
		Creds:   map[string]string{},
		HttpSpec: &HttpRequestSpec{
			URL:    baseURL + "/upload",
			Method: "POST",
			MultipartFields: map[string]MultipartField{
				"qqfile": {Type: "file", Value: imagePath},
			},
			ResponseParser: ResponseParserSpec{
				Type:         "json",
				StatusPath:   "success",
				SuccessValue: "true",
				URLPath:      "newUrl",
			},
		},
		ResolveSpec: &core.BatchResolveSpec{
			ResultURL:        "{url}",
			LinkExtractor:    `(?is)\[url=(?P<image_url>https?://[^\]\s]+/p/[0-9]+/(?P<filename>[^/\]\s]+)\.html)\]\s*\[img\](?P<thumb_url>https?://[^\]\s]+)\[/img\]\s*\[/url\]`,
			GalleryExtractor: "input#imgCodeGG",
			FileMatchMode:    "filename",
		},
	}

	result, err := core.ExecuteHttpUploadWithData(context.Background(), server.Client(), imagePath, job)
	if err != nil {
		t.Fatalf("ExecuteHttpUpload failed: %v", err)
	}
	if result.URL != "https://www.turboimagehost.com/p/124/turbo-upload.jpg.html" {
		t.Fatalf("url = %q", result.URL)
	}
	if result.Thumb != "https://s8d8.turboimg.net/t1/124_turbo-upload.jpg" {
		t.Fatalf("thumb = %q", result.Thumb)
	}
	if result.Data["gallery_url"] != "https://www.turboimagehost.com/album/394761/miscellaneous" {
		t.Fatalf("gallery_url = %q", result.Data["gallery_url"])
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

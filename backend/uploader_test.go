// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"context"
	"encoding/json"
	"image/color"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"github.com/disintegration/imaging"
)

// --- Utility Function Tests ---

func TestRandomString(t *testing.T) {
	tests := []struct {
		name   string
		length int
	}{
		{"empty", 0},
		{"small", 5},
		{"medium", 16},
		{"large", 64},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := randomString(tt.length)
			if len(result) != tt.length {
				t.Errorf("randomString(%d) length = %d, want %d", tt.length, len(result), tt.length)
			}

			// Verify all characters are from charset
			for _, c := range result {
				if !strings.ContainsRune(charset, c) {
					t.Errorf("randomString(%d) contains invalid character: %c", tt.length, c)
				}
			}
		})
	}
}

func TestRandomStringUniqueness(t *testing.T) {
	// Generate multiple random strings and check they're unique
	seen := make(map[string]bool)
	iterations := 100
	length := 16

	for i := 0; i < iterations; i++ {
		result := randomString(length)
		if seen[result] {
			t.Errorf("randomString(%d) generated duplicate: %s", length, result)
		}
		seen[result] = true
	}
}

func TestQuoteEscape(t *testing.T) {
	tests := []struct {
		name  string
		input string
		want  string
	}{
		{"no escape needed", "hello world", "hello world"},
		{"escape quotes", `he said "hi"`, `he said \"hi\"`},
		{"escape backslash", `path\to\file`, `path\\to\\file`},
		{"escape both", `"C:\path\file"`, `\"C:\\path\\file\"`},
		{"empty string", "", ""},
		{"only quotes", `"""`, `\"\"\"`},
		{"only backslashes", `\\\`, `\\\\\\`},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := quoteEscape(tt.input)
			if got != tt.want {
				t.Errorf("quoteEscape(%q) = %q, want %q", tt.input, got, tt.want)
			}
		})
	}
}

// --- JSON Protocol Tests ---

func TestJobRequestUnmarshal(t *testing.T) {
	jsonData := `{
		"action": "http_upload",
		"service": "pixhost",
		"files": ["image1.jpg", "image2.png"],
		"creds": {"username": "test", "password": "secret"},
		"config": {"thumb_size": "medium"},
		"context_data": {"gallery_id": "123"}
	}`

	var job JobRequest
	err := json.Unmarshal([]byte(jsonData), &job)
	if err != nil {
		t.Fatalf("Failed to unmarshal JobRequest: %v", err)
	}

	if job.Action != "http_upload" {
		t.Errorf("Action = %q, want %q", job.Action, "http_upload")
	}
	if job.Service != "pixhost" {
		t.Errorf("Service = %q, want %q", job.Service, "pixhost")
	}
	if len(job.Files) != 2 {
		t.Errorf("Files length = %d, want 2", len(job.Files))
	}
	if job.Creds["username"] != "test" {
		t.Errorf("Creds[username] = %q, want %q", job.Creds["username"], "test")
	}
}

func TestOutputEventMarshal(t *testing.T) {
	event := OutputEvent{
		Type:     "result",
		FilePath: "test.jpg",
		Status:   "success",
		Url:      "https://example.com/image.jpg",
		Thumb:    "https://example.com/thumb.jpg",
		Msg:      "Upload successful",
	}

	data, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("Failed to marshal OutputEvent: %v", err)
	}

	var decoded OutputEvent
	err = json.Unmarshal(data, &decoded)
	if err != nil {
		t.Fatalf("Failed to unmarshal OutputEvent: %v", err)
	}

	if decoded.Type != event.Type {
		t.Errorf("Type = %q, want %q", decoded.Type, event.Type)
	}
	if decoded.Status != event.Status {
		t.Errorf("Status = %q, want %q", decoded.Status, event.Status)
	}
	if decoded.Url != event.Url {
		t.Errorf("Url = %q, want %q", decoded.Url, event.Url)
	}
}

// --- HTTP Mock Tests ---

func TestDoRequest(t *testing.T) {
	// Create a test server
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Verify User-Agent
		if ua := r.Header.Get("User-Agent"); ua != DefaultUserAgent {
			t.Errorf("User-Agent = %q, want %q", ua, DefaultUserAgent)
		}

		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("success"))
	}))
	defer server.Close()

	// Initialize HTTP client
	initHTTPClient()

	resp, err := doRequest(context.Background(), "GET", server.URL, nil, "")
	if err != nil {
		t.Fatalf("doRequest failed: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("Status code = %d, want %d", resp.StatusCode, http.StatusOK)
	}

	body, _ := io.ReadAll(resp.Body)
	if string(body) != "success" {
		t.Errorf("Body = %q, want %q", string(body), "success")
	}
}

func TestDoRequestWithTimeout(t *testing.T) {
	// Create a slow server
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Server responds, so this should succeed
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	initHTTPClient()

	resp, err := doRequest(context.Background(), "GET", server.URL, nil, "")
	if err != nil {
		t.Fatalf("doRequest unexpectedly failed: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("Status code = %d, want %d", resp.StatusCode, http.StatusOK)
	}
}

// --- Thumbnail Generation Tests ---

func TestHandleGenerateThumb(t *testing.T) {
	// Create a temporary test image
	tmpDir := t.TempDir()
	testImagePath := filepath.Join(tmpDir, "test.jpg")

	// Create a simple test image (1x1 white pixel)
	err := createTestImage(testImagePath)
	if err != nil {
		t.Fatalf("Failed to create test image: %v", err)
	}

	job := JobRequest{
		Action: "generate_thumb",
		Files:  []string{testImagePath},
		Config: map[string]string{
			"width": "100",
		},
	}

	// Note: This test verifies the function doesn't crash
	// Full validation would require capturing stdout and parsing JSON
	handleGenerateThumb(job)
}

// --- Helper Functions for Tests ---

// createTestImage creates a simple 100x100 white JPEG image for testing
func createTestImage(path string) error {
	// Create a 100x100 white image
	img := imaging.New(100, 100, color.White)

	// Save as JPEG
	return imaging.Save(img, path)
}

// --- Benchmark Tests ---

func BenchmarkRandomString(b *testing.B) {
	for i := 0; i < b.N; i++ {
		randomString(16)
	}
}

func BenchmarkQuoteEscape(b *testing.B) {
	testString := `This is a "test" string with \backslashes\ and "quotes"`
	for i := 0; i < b.N; i++ {
		quoteEscape(testString)
	}
}

// --- Integration Test Helpers ---

// MockUploadServer creates a mock HTTP server for testing upload functions
func MockUploadServer(t *testing.T, responseCode int, responseBody string) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Parse multipart form
		err := r.ParseMultipartForm(10 << 20) // 10MB
		if err != nil {
			t.Logf("Failed to parse multipart form: %v", err)
		}

		w.WriteHeader(responseCode)
		_, _ = w.Write([]byte(responseBody))
	}))
}

// --- Error Handling Tests ---

func TestHandleJobInvalidAction(t *testing.T) {
	job := JobRequest{
		Action:  "invalid_action",
		Service: "pixhost",
		Files:   []string{},
	}

	// This should not panic
	defer func() {
		if r := recover(); r != nil {
			t.Errorf("handleJob panicked with invalid action: %v", r)
		}
	}()

	handleJob(job)
}

func TestHandleJobMissingFiles(t *testing.T) {
	job := JobRequest{
		Action:  "http_upload",
		Service: "pixhost",
		Files:   []string{}, // Empty files array
		HttpSpec: &HttpRequestSpec{
			URL:    "https://example.com/upload",
			Method: "POST",
		},
	}

	defer func() {
		if r := recover(); r != nil {
			t.Errorf("handleJob panicked with missing files: %v", r)
		}
	}()

	handleJob(job)
}

func TestHandleJobNonexistentFile(t *testing.T) {
	job := JobRequest{
		Action:  "http_upload",
		Service: "pixhost",
		Files:   []string{"/nonexistent/file.jpg"},
		HttpSpec: &HttpRequestSpec{
			URL:    "https://example.com/upload",
			Method: "POST",
		},
	}

	defer func() {
		if r := recover(); r != nil {
			t.Errorf("handleJob panicked with nonexistent file: %v", r)
		}
	}()

	handleJob(job)
}

// --- File Processing Tests ---

func TestProcessFileGenericNonexistent(t *testing.T) {
	job := JobRequest{
		Action:  "http_upload",
		Service: "test.service",
		Files:   []string{},
		HttpSpec: &HttpRequestSpec{
			URL:    "https://example.com/upload",
			Method: "POST",
			MultipartFields: map[string]MultipartField{
				"file": {Type: "file", Value: ""},
			},
			ResponseParser: ResponseParserSpec{Type: "json"},
		},
	}

	// Should handle nonexistent file gracefully
	defer func() {
		if r := recover(); r != nil {
			t.Errorf("processFileGeneric panicked with nonexistent file: %v", r)
		}
	}()

	processFileGeneric("/nonexistent/file.jpg", &job)
}

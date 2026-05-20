// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// --- handleJob Tests ---

func TestHandleJobUnknownAction(t *testing.T) {
	initHTTPClient()

	job := JobRequest{
		Action: "unknown_action",
		Files:  []string{},
	}

	// Should not panic
	handleJob(job)
}

func TestHandleJobGenerateThumb(t *testing.T) {
	initHTTPClient()

	job := JobRequest{
		Action: "generate_thumb",
		Files:  []string{},
	}

	// Should not panic
	handleJob(job)
}

func TestHandleJobViperLogin(t *testing.T) {
	initHTTPClient()

	job := JobRequest{
		Action:  "viper_login",
		Service: "vipr.im",
		Config: map[string]string{
			"username": "testuser",
			"password": "testpass",
		},
	}

	// Should not panic
	handleJob(job)
}

func TestHandleJobViperPost(t *testing.T) {
	initHTTPClient()

	job := JobRequest{
		Action:  "viper_post",
		Service: "vipr.im",
		Config:  map[string]string{},
	}

	// Should not panic
	handleJob(job)
}

// --- waitForRateLimit Tests ---

func TestWaitForRateLimitSuccess(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping rate limit test in short mode")
	}

	service := "test.ratelimit.success"
	ctx := context.Background()

	// Should complete without error
	err := waitForRateLimit(ctx, service)
	if err != nil {
		t.Errorf("waitForRateLimit() error = %v, want nil", err)
	}
}

func TestWaitForRateLimitContextTimeout(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping rate limit test in short mode")
	}

	service := "test.ratelimit.timeout"
	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Millisecond)
	defer cancel()

	// Create a limiter and exhaust it
	limiter := getRateLimiter(service)
	for i := 0; i < 10; i++ {
		_ = limiter.Wait(context.Background())
	}

	// This should fail due to context timeout
	err := waitForRateLimit(ctx, service)
	if err == nil {
		t.Error("waitForRateLimit() should return error on context timeout")
	}
}

// --- doRequest Tests ---

func TestDoRequestBasic(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping HTTP test in short mode")
	}

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("test response"))
	}))
	defer server.Close()

	initHTTPClient()
	ctx := context.Background()

	resp, err := doRequest(ctx, "GET", server.URL, nil, "")
	if err != nil {
		t.Errorf("doRequest() error = %v, want nil", err)
	}
	if resp == nil {
		t.Error("doRequest() response is nil")
	}
}

func TestDoRequestWithPost(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping HTTP test in short mode")
	}

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" {
			t.Errorf("Expected POST, got %s", r.Method)
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("success"))
	}))
	defer server.Close()

	initHTTPClient()
	ctx := context.Background()

	resp, err := doRequest(ctx, "POST", server.URL, nil, "application/json")
	if err != nil {
		t.Errorf("doRequest() error = %v, want nil", err)
	}
	if resp == nil {
		t.Error("doRequest() response is nil")
	}
}

// --- Concurrency Tests ---

func TestSendJSONConcurrent(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping concurrency test in short mode")
	}

	iterations := 20
	done := make(chan bool, iterations)

	for i := 0; i < iterations; i++ {
		go func(id int) {
			event := OutputEvent{
				Type: "test",
				Msg:  "Concurrent test",
			}
			sendJSON(event)
			done <- true
		}(i)
	}

	for i := 0; i < iterations; i++ {
		<-done
	}
}

// --- JobRequest Structure Tests ---

func TestJobRequestAllFields(t *testing.T) {
	job := JobRequest{
		Action:  "upload",
		Service: "imx.to",
		Files:   []string{"/path/to/file1.jpg", "/path/to/file2.jpg"},
		Config: map[string]string{
			"api_key":     "test123",
			"gallery_id":  "456",
			"upload_size": "medium",
		},
		HttpSpec: &HttpRequestSpec{
			URL:    "https://example.com/upload",
			Method: "POST",
		},
	}

	if job.Action != "upload" {
		t.Errorf("Action = %q, want %q", job.Action, "upload")
	}
	if job.Service != "imx.to" {
		t.Errorf("Service = %q, want %q", job.Service, "imx.to")
	}
	if len(job.Files) != 2 {
		t.Errorf("Files count = %d, want 2", len(job.Files))
	}
	if len(job.Config) != 3 {
		t.Errorf("Config count = %d, want 3", len(job.Config))
	}
	if job.HttpSpec == nil {
		t.Error("HttpSpec should not be nil")
	}
}

// --- MultipartField Tests ---

func TestMultipartFieldTypes(t *testing.T) {
	tests := []struct {
		name      string
		fieldType string
		value     string
	}{
		{"file field", "file", "/path/to/file.jpg"},
		{"text field", "text", "some text value"},
		{"template field", "template", "{csrf_token}"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			field := MultipartField{
				Type:  tt.fieldType,
				Value: tt.value,
			}

			if field.Type != tt.fieldType {
				t.Errorf("Type = %q, want %q", field.Type, tt.fieldType)
			}
			if field.Value != tt.value {
				t.Errorf("Value = %q, want %q", field.Value, tt.value)
			}
		})
	}
}

// --- Context Cancellation Tests ---

func TestWaitForRateLimitCancellation(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping context test in short mode")
	}

	service := "test.cancel"
	ctx, cancel := context.WithCancel(context.Background())

	// Cancel immediately
	cancel()

	err := waitForRateLimit(ctx, service)
	if err == nil {
		t.Error("waitForRateLimit() should return error when context is cancelled")
	}
}

// --- Edge Case Tests ---

func TestGetJSONValueWithNilInPath(t *testing.T) {
	data := map[string]interface{}{
		"level1": map[string]interface{}{
			"level2": nil,
		},
	}

	result := getJSONValue(data, "level1.level2.level3")
	if result != "" {
		t.Errorf("getJSONValue() with nil in path = %q, want empty string", result)
	}
}


// --- Benchmark Additional Tests ---

func BenchmarkRateLimiterAccess(b *testing.B) {
	service := "bench.test"

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		getRateLimiter(service)
	}
}

func BenchmarkHandleJob(b *testing.B) {
	initHTTPClient()

	job := JobRequest{
		Action: "unknown_action",
		Files:  []string{},
	}

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		handleJob(job)
	}
}

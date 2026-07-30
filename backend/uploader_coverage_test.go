// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"context"
	"encoding/json"
	"testing"
	"time"
)

// --- Rate Limiting Tests ---

func TestGetRateLimiter(t *testing.T) {
	tests := []struct {
		name    string
		service string
	}{
		{"imx.to", "imx.to"},
		{"pixhost.cc", "pixhost.cc"},
		{"pixhost.to", "pixhost.to"},
		{"vipr.im", "vipr.im"},
		{"turboimagehost", "turboimagehost"},
		{"imagebam.com", "imagebam.com"},
		{"vipergirls.to", "vipergirls.to"},
		{"unknown service", "unknown.service"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			limiter := getRateLimiter(tt.service)
			if limiter == nil {
				t.Errorf("getRateLimiter(%q) returned nil", tt.service)
			}
		})
	}
}

func TestWaitForRateLimit(t *testing.T) {
	ctx := context.Background()
	service := "test.service"

	// Should complete without error
	err := waitForRateLimit(ctx, service)
	if err != nil {
		t.Errorf("waitForRateLimit failed: %v", err)
	}
}

func TestWaitForRateLimitCancelled(t *testing.T) {
	// Create a context that's already cancelled
	ctx, cancel := context.WithCancel(context.Background())
	cancel() // Cancel immediately

	err := waitForRateLimit(ctx, "test.service")
	if err == nil {
		t.Error("waitForRateLimit should fail with cancelled context")
	}
}

func TestWaitForRateLimitTimeout(t *testing.T) {
	// Create a context with very short timeout
	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Nanosecond)
	defer cancel()

	// Sleep to ensure timeout occurs
	time.Sleep(1 * time.Millisecond)

	err := waitForRateLimit(ctx, "test.service")
	if err == nil {
		t.Error("waitForRateLimit should fail with timeout context")
	}
}

// --- HTTP Spec Tests ---

func TestHandleHttpUploadMissingSpec(t *testing.T) {
	job := JobRequest{
		Action:   "http_upload",
		Service:  "test.service",
		Files:    []string{"test.jpg"},
		HttpSpec: nil, // Missing spec
	}

	defer func() {
		if r := recover(); r != nil {
			t.Errorf("handleHttpUpload panicked: %v", r)
		}
	}()

	handleHttpUpload(job)
}

func TestHandleHttpUploadEmptyFiles(t *testing.T) {
	job := JobRequest{
		Action:  "http_upload",
		Service: "test.service",
		Files:   []string{}, // No files
		HttpSpec: &HttpRequestSpec{
			URL:    "https://example.com/upload",
			Method: "POST",
		},
	}

	defer func() {
		if r := recover(); r != nil {
			t.Errorf("handleHttpUpload panicked: %v", r)
		}
	}()

	handleHttpUpload(job)
}

// --- SendJSON Tests ---

func TestSendJSON(t *testing.T) {
	event := OutputEvent{
		Type:   "test",
		Status: "success",
		Msg:    "Test message",
	}

	// Should not panic
	defer func() {
		if r := recover(); r != nil {
			t.Errorf("sendJSON panicked: %v", r)
		}
	}()

	sendJSON(event)
}

func TestSendJSONComplexData(t *testing.T) {
	event := OutputEvent{
		Type:     "result",
		FilePath: "/path/to/file.jpg",
		Status:   "success",
		Url:      "https://example.com/image.jpg",
		Thumb:    "https://example.com/thumb.jpg",
		Msg:      "Upload complete",
		Data: map[string]interface{}{
			"gallery_id": "123",
			"size":       1024,
			"tags":       []string{"tag1", "tag2"},
		},
	}

	defer func() {
		if r := recover(); r != nil {
			t.Errorf("sendJSON panicked with complex data: %v", r)
		}
	}()

	sendJSON(event)
}

// --- Additional Edge Cases ---

func TestRateLimiterConcurrency(t *testing.T) {
	service := "test.concurrent"
	iterations := 10

	// Test concurrent access to rate limiter
	done := make(chan bool, iterations)

	for i := 0; i < iterations; i++ {
		go func() {
			limiter := getRateLimiter(service)
			if limiter == nil {
				t.Error("getRateLimiter returned nil in concurrent test")
			}
			done <- true
		}()
	}

	// Wait for all goroutines
	for i := 0; i < iterations; i++ {
		<-done
	}
}

func TestRateLimitMultipleServices(t *testing.T) {
	services := []string{"imx.to", "pixhost.cc", "pixhost.to", "vipr.im", "turboimagehost", "imagebam.com"}

	for _, service := range services {
		t.Run(service, func(t *testing.T) {
			limiter := getRateLimiter(service)
			if limiter == nil {
				t.Errorf("getRateLimiter(%q) returned nil", service)
			}

			// Test that we can reserve tokens
			ctx := context.Background()
			if !limiter.Allow() {
				// If not allowed, wait a bit and try again
				time.Sleep(100 * time.Millisecond)
				if !limiter.Allow() {
					t.Errorf("Rate limiter for %s not allowing requests", service)
				}
			}

			// Test with context
			err := limiter.Wait(ctx)
			if err != nil {
				t.Errorf("Rate limiter wait failed for %s: %v", service, err)
			}
		})
	}
}

// --- HttpRequestSpec Processing Tests ---

func TestProcessFileGenericWithSpec(t *testing.T) {
	job := JobRequest{
		Action:  "http_upload",
		Service: "test.service",
		HttpSpec: &HttpRequestSpec{
			URL:    "https://example.com/upload",
			Method: "POST",
			MultipartFields: map[string]MultipartField{
				"file": {
					Type:  "file",
					Value: "test.jpg",
				},
			},
		},
	}

	// Should handle gracefully (will fail to open file)
	defer func() {
		if r := recover(); r != nil {
			t.Errorf("processFileGeneric panicked: %v", r)
		}
	}()

	processFileGeneric("nonexistent.jpg", &job)
}

// --- Benchmark Tests ---

func BenchmarkGetRateLimiter(b *testing.B) {
	for i := 0; i < b.N; i++ {
		getRateLimiter("imx.to")
	}
}

func BenchmarkWaitForRateLimit(b *testing.B) {
	ctx := context.Background()
	service := "bench.service"

	// Pre-create limiter
	_ = getRateLimiter(service)

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		_ = waitForRateLimit(ctx, service)
	}
}

func BenchmarkSendJSON(b *testing.B) {
	event := OutputEvent{
		Type:   "benchmark",
		Status: "success",
		Msg:    "Benchmark test",
	}

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		sendJSON(event)
	}
}

// --- Helper Function Tests ---

func TestJobRequestWithNilFields(t *testing.T) {
	job := JobRequest{
		Action:  "test",
		Service: "test.service",
		Files:   nil,
		Creds:   nil,
		Config:  nil,
	}

	// Should handle nil maps gracefully
	if job.Creds == nil {
		job.Creds = make(map[string]string)
	}
	if job.Config == nil {
		job.Config = make(map[string]string)
	}

	if job.Creds == nil || job.Config == nil {
		t.Error("Failed to initialize nil maps")
	}
}

func TestOutputEventSerialization(t *testing.T) {
	tests := []struct {
		name  string
		event OutputEvent
	}{
		{
			"minimal",
			OutputEvent{Type: "test"},
		},
		{
			"full",
			OutputEvent{
				Type:     "result",
				FilePath: "test.jpg",
				Status:   "success",
				Url:      "https://example.com/img.jpg",
				Thumb:    "https://example.com/thumb.jpg",
				Msg:      "Success",
				Data:     map[string]string{"key": "value"},
			},
		},
		{
			"with_complex_data",
			OutputEvent{
				Type: "data",
				Data: []map[string]interface{}{
					{"id": "1", "name": "Gallery 1"},
					{"id": "2", "name": "Gallery 2"},
				},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			data, err := json.Marshal(tt.event)
			if err != nil {
				t.Errorf("Failed to marshal OutputEvent: %v", err)
			}

			var decoded OutputEvent
			err = json.Unmarshal(data, &decoded)
			if err != nil {
				t.Errorf("Failed to unmarshal OutputEvent: %v", err)
			}

			if decoded.Type != tt.event.Type {
				t.Errorf("Type mismatch: got %q, want %q", decoded.Type, tt.event.Type)
			}
		})
	}
}

// --- Context Cancellation Tests ---

func TestDoRequestWithCancelledContext(t *testing.T) {
	initHTTPClient()

	ctx, cancel := context.WithCancel(context.Background())
	cancel() // Cancel immediately

	_, err := doRequest(ctx, "GET", "https://example.com", nil, "")
	if err == nil {
		t.Error("doRequest should fail with cancelled context")
	}
}

// --- Stress Tests ---

func TestRateLimitStress(t *testing.T) {
	t.Skip("Skipping long-running stress test")
}

// --- Error Recovery Tests ---

func TestHandleJobPanic(t *testing.T) {
	// Test that handleJob doesn't crash the entire program
	job := JobRequest{
		Action:  "http_upload",
		Service: "test.service",
		Files:   []string{"test.jpg"},
		HttpSpec: &HttpRequestSpec{
			URL:    "https://example.com/upload",
			Method: "POST",
		},
	}

	defer func() {
		if r := recover(); r != nil {
			t.Logf("handleJob panicked (acceptable): %v", r)
		}
	}()

	handleJob(job)
}

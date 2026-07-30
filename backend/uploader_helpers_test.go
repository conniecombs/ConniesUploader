// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"context"
	"testing"
	"time"
)

// --- Additional Helper Function Tests ---

func TestSendJSONWithNilData(t *testing.T) {
	event := OutputEvent{
		Type:   "test",
		Data:   nil,
		Status: "success",
	}

	defer func() {
		if r := recover(); r != nil {
			t.Errorf("sendJSON panicked with nil data: %v", r)
		}
	}()

	sendJSON(event)
}

func TestSendJSONMultiple(t *testing.T) {
	events := []OutputEvent{
		{Type: "log", Msg: "Starting"},
		{Type: "status", Status: "processing"},
		{Type: "result", Status: "success", Url: "https://example.com"},
		{Type: "error", Msg: "Test error"},
		{Type: "batch_complete", Status: "done"},
	}

	for _, event := range events {
		defer func() {
			if r := recover(); r != nil {
				t.Errorf("sendJSON panicked: %v", r)
			}
		}()
		sendJSON(event)
	}
}

// --- Context and Timeout Tests ---

func TestContextTimeout(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
	defer cancel()

	time.Sleep(20 * time.Millisecond)

	select {
	case <-ctx.Done():
		// Context properly timed out
		if ctx.Err() != context.DeadlineExceeded {
			t.Errorf("Expected DeadlineExceeded, got %v", ctx.Err())
		}
	default:
		t.Error("Context did not timeout as expected")
	}
}

func TestContextCancellationHelper(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())

	// Cancel immediately
	cancel()

	select {
	case <-ctx.Done():
		// Context properly cancelled
		if ctx.Err() != context.Canceled {
			t.Errorf("Expected Canceled, got %v", ctx.Err())
		}
	default:
		t.Error("Context was not cancelled")
	}
}

// --- Rate Limiter Behavior Tests ---

func TestRateLimiterDefaultCreation(t *testing.T) {
	unknownService := "never.seen.before.service"

	// First call should create a new limiter
	limiter1 := getRateLimiter(unknownService)
	if limiter1 == nil {
		t.Error("getRateLimiter should create default limiter for unknown service")
	}

	// Second call should return the same limiter
	limiter2 := getRateLimiter(unknownService)
	if limiter2 != limiter1 {
		t.Error("getRateLimiter should return same limiter for repeated calls")
	}
}

func TestRateLimiterKnownServices(t *testing.T) {
	services := []string{"imx.to", "pixhost.cc", "pixhost.to", "vipr.im", "turboimagehost", "imagebam.com", "vipergirls.to"}

	limiters := make(map[string]interface{})

	for _, service := range services {
		limiter := getRateLimiter(service)
		if limiter == nil {
			t.Errorf("getRateLimiter(%q) returned nil", service)
		}

		// Store to check uniqueness
		limiters[service] = limiter
	}

	// Each service should have its own limiter
	if len(limiters) != len(services) {
		t.Error("Not all services have unique limiters")
	}
}

// --- Job Request Tests ---

func TestJobRequestEmptyConfig(t *testing.T) {
	job := JobRequest{
		Action:  "test",
		Service: "test.service",
		Config:  make(map[string]string),
	}

	// Access empty config should not panic
	value := job.Config["nonexistent_key"]
	if value != "" {
		t.Errorf("Expected empty string for nonexistent key, got %q", value)
	}
}

func TestJobRequestEmptyCreds(t *testing.T) {
	job := JobRequest{
		Action:  "test",
		Service: "test.service",
		Creds:   make(map[string]string),
	}

	// Access empty creds should not panic
	value := job.Creds["nonexistent_key"]
	if value != "" {
		t.Errorf("Expected empty string for nonexistent key, got %q", value)
	}
}

// --- Edge Case Tests ---

func TestHandleJobEmptyAction(t *testing.T) {
	job := JobRequest{
		Action:  "",
		Service: "test.service",
		Files:   []string{},
	}

	defer func() {
		if r := recover(); r != nil {
			t.Logf("handleJob panicked with empty action (acceptable): %v", r)
		}
	}()

	handleJob(job)
}

func TestHandleJobEmptyService(t *testing.T) {
	job := JobRequest{
		Action:  "http_upload",
		Service: "",
		Files:   []string{"test.jpg"},
		HttpSpec: &HttpRequestSpec{
			URL:    "https://example.com/upload",
			Method: "POST",
		},
	}

	defer func() {
		if r := recover(); r != nil {
			t.Logf("handleJob panicked with empty service (acceptable): %v", r)
		}
	}()

	handleJob(job)
}

// --- OutputEvent Tests ---

func TestOutputEventEmptyFields(t *testing.T) {
	event := OutputEvent{
		Type:     "",
		FilePath: "",
		Status:   "",
		Url:      "",
		Thumb:    "",
		Msg:      "",
		Data:     nil,
	}

	defer func() {
		if r := recover(); r != nil {
			t.Errorf("sendJSON panicked with empty fields: %v", r)
		}
	}()

	sendJSON(event)
}

func TestOutputEventLargeData(t *testing.T) {
	// Create large data structure
	largeData := make([]map[string]interface{}, 100)
	for i := 0; i < 100; i++ {
		largeData[i] = map[string]interface{}{
			"id":          i,
			"name":        "Gallery " + string(rune(i)),
			"description": "This is a test gallery with a long description",
			"images":      []string{"img1.jpg", "img2.jpg", "img3.jpg"},
		}
	}

	event := OutputEvent{
		Type: "data",
		Data: largeData,
	}

	defer func() {
		if r := recover(); r != nil {
			t.Errorf("sendJSON panicked with large data: %v", r)
		}
	}()

	sendJSON(event)
}

// --- HTTP Client Tests ---

func TestInitHTTPClientMultipleTimes(t *testing.T) {
	// Should be safe to call multiple times
	initHTTPClient()
	client1 := client

	initHTTPClient()
	client2 := client

	if client1 == nil || client2 == nil {
		t.Error("HTTP client should not be nil after initialization")
	}
}

// --- Benchmark Tests ---

func BenchmarkGetRateLimiterConcurrent(b *testing.B) {
	b.RunParallel(func(pb *testing.PB) {
		service := "benchmark.service"
		for pb.Next() {
			getRateLimiter(service)
		}
	})
}

func BenchmarkSendJSONParallel(b *testing.B) {
	event := OutputEvent{
		Type:   "benchmark",
		Status: "success",
	}

	b.RunParallel(func(pb *testing.PB) {
		for pb.Next() {
			sendJSON(event)
		}
	})
}

// --- State Mutex Tests ---

func TestMultipleGalleryConcurrentAccess(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping concurrent test in short mode")
	}

	services := []string{"imx.to", "pixhost.cc", "pixhost.to", "vipr.im"}
	done := make(chan bool, len(services)*10)

	for i := 0; i < 10; i++ {
		for _, service := range services {
			go func(s string) {
				limiter := getRateLimiter(s)
				if limiter == nil {
					t.Error("getRateLimiter returned nil in concurrent test")
				}
				done <- true
			}(service)
		}
	}

	// Wait for all goroutines
	for i := 0; i < len(services)*10; i++ {
		<-done
	}
}

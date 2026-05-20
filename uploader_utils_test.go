// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"testing"
)

// --- getJSONValue Tests ---

func TestGetJSONValueSimple(t *testing.T) {
	data := map[string]interface{}{
		"user":   "testuser",
		"id":     float64(123),
		"active": true,
	}

	tests := []struct {
		name     string
		path     string
		expected string
	}{
		{"string field", "user", "testuser"},
		{"number field", "id", "123"},
		{"boolean field", "active", "true"},
		{"non-existent field", "missing", ""},
		{"empty path", "", ""},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := getJSONValue(data, tt.path)
			if result != tt.expected {
				t.Errorf("getJSONValue(%q) = %q, want %q", tt.path, result, tt.expected)
			}
		})
	}
}

func TestGetJSONValueNested(t *testing.T) {
	data := map[string]interface{}{
		"gallery": map[string]interface{}{
			"id":   "abc123",
			"name": "Test Gallery",
			"metadata": map[string]interface{}{
				"count": float64(5),
				"owner": "testuser",
			},
		},
	}

	tests := []struct {
		name     string
		path     string
		expected string
	}{
		{"nested string", "gallery.id", "abc123"},
		{"nested name", "gallery.name", "Test Gallery"},
		{"deep nested", "gallery.metadata.owner", "testuser"},
		{"deep nested number", "gallery.metadata.count", "5"},
		{"invalid path", "gallery.missing.field", ""},
		{"partial path", "gallery.metadata", ""},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := getJSONValue(data, tt.path)
			if result != tt.expected {
				t.Errorf("getJSONValue(%q) = %q, want %q", tt.path, result, tt.expected)
			}
		})
	}
}

func TestGetJSONValueTypeConversions(t *testing.T) {
	tests := []struct {
		name     string
		data     map[string]interface{}
		path     string
		expected string
	}{
		{
			"integer",
			map[string]interface{}{"count": float64(42)},
			"count",
			"42",
		},
		{
			"float",
			map[string]interface{}{"price": float64(19.99)},
			"price",
			"20",
		},
		{
			"boolean true",
			map[string]interface{}{"enabled": true},
			"enabled",
			"true",
		},
		{
			"boolean false",
			map[string]interface{}{"enabled": false},
			"enabled",
			"false",
		},
		{
			"null value",
			map[string]interface{}{"value": nil},
			"value",
			"",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := getJSONValue(tt.data, tt.path)
			if result != tt.expected {
				t.Errorf("getJSONValue(%q) = %q, want %q", tt.path, result, tt.expected)
			}
		})
	}
}

func TestGetJSONValueEdgeCases(t *testing.T) {
	// Test with array values (should return empty)
	dataWithArray := map[string]interface{}{
		"items": []interface{}{"item1", "item2"},
	}
	result := getJSONValue(dataWithArray, "items")
	if result != "" {
		t.Errorf("getJSONValue with array should return empty, got %q", result)
	}

	// Test with empty map
	emptyData := map[string]interface{}{}
	result = getJSONValue(emptyData, "test")
	if result != "" {
		t.Errorf("getJSONValue with empty map should return empty, got %q", result)
	}

	// Test with complex nested structure
	complexData := map[string]interface{}{
		"level1": map[string]interface{}{
			"level2": map[string]interface{}{
				"level3": "deep_value",
			},
		},
	}
	result = getJSONValue(complexData, "level1.level2.level3")
	if result != "deep_value" {
		t.Errorf("getJSONValue with deep nesting = %q, want %q", result, "deep_value")
	}
}


// --- ResponseParserSpec Tests ---

func TestResponseParserSpecTypes(t *testing.T) {
	types := []string{"json", "html", "regex", "direct"}

	for _, parserType := range types {
		t.Run(parserType, func(t *testing.T) {
			parser := &ResponseParserSpec{
				Type:    parserType,
				URLPath: "test.path",
			}

			if parser.Type != parserType {
				t.Errorf("Type = %q, want %q", parser.Type, parserType)
			}
		})
	}
}

func TestResponseParserSpecFields(t *testing.T) {
	parser := &ResponseParserSpec{
		Type:         "json",
		URLPath:      "data.url",
		ThumbPath:    "data.thumb",
		StatusPath:   "status",
		SuccessValue: "ok",
	}

	if parser.Type != "json" {
		t.Errorf("Type = %q, want %q", parser.Type, "json")
	}
	if parser.URLPath != "data.url" {
		t.Errorf("URLPath = %q, want %q", parser.URLPath, "data.url")
	}
	if parser.StatusPath != "status" {
		t.Errorf("StatusPath = %q, want %q", parser.StatusPath, "status")
	}
}

// --- Benchmark Tests ---

func BenchmarkGetJSONValueSimple(b *testing.B) {
	data := map[string]interface{}{
		"user": "testuser",
		"id":   float64(123),
	}

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		getJSONValue(data, "user")
	}
}

func BenchmarkGetJSONValueNested(b *testing.B) {
	data := map[string]interface{}{
		"level1": map[string]interface{}{
			"level2": map[string]interface{}{
				"level3": "value",
			},
		},
	}

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		getJSONValue(data, "level1.level2.level3")
	}
}


// --- Additional HttpRequestSpec Tests ---

func TestHttpRequestSpecComplete(t *testing.T) {
	spec := &HttpRequestSpec{
		URL:    "https://example.com/upload",
		Method: "POST",
		Headers: map[string]string{
			"Content-Type":  "multipart/form-data",
			"Authorization": "Bearer token123",
		},
		MultipartFields: map[string]MultipartField{
			"file": {
				Type:  "file",
				Value: "test.jpg",
			},
			"title": {
				Type:  "text",
				Value: "Test Image",
			},
			"description": {
				Type:  "text",
				Value: "A test upload",
			},
		},
		ResponseParser: ResponseParserSpec{
			Type:    "json",
			URLPath: "data.url",
		},
	}

	// Verify all fields are set correctly
	if spec.URL != "https://example.com/upload" {
		t.Errorf("URL = %q, want %q", spec.URL, "https://example.com/upload")
	}
	if spec.Method != "POST" {
		t.Errorf("Method = %q, want %q", spec.Method, "POST")
	}
	if len(spec.Headers) != 2 {
		t.Errorf("Headers count = %d, want 2", len(spec.Headers))
	}
	if len(spec.MultipartFields) != 3 {
		t.Errorf("MultipartFields count = %d, want 3", len(spec.MultipartFields))
	}
	if spec.ResponseParser.Type != "json" {
		t.Errorf("ResponseParser.Type = %q, want %q", spec.ResponseParser.Type, "json")
	}
}

func TestPreRequestSpecComplete(t *testing.T) {
	spec := &PreRequestSpec{
		Action:  "login",
		URL:     "https://example.com/login",
		Method:  "POST",
		Headers: map[string]string{"Content-Type": "application/json"},
		FormFields: map[string]string{
			"username": "testuser",
			"password": "testpass",
		},
		UseCookies: true,
		ExtractFields: map[string]string{
			"token": "auth_token",
		},
		ResponseType: "json",
	}

	// Verify all fields
	if spec.Action != "login" {
		t.Errorf("Action = %q, want %q", spec.Action, "login")
	}
	if !spec.UseCookies {
		t.Error("UseCookies should be true")
	}
	if len(spec.ExtractFields) != 1 {
		t.Errorf("ExtractFields count = %d, want 1", len(spec.ExtractFields))
	}
	if spec.ResponseType != "json" {
		t.Errorf("ResponseType = %q, want %q", spec.ResponseType, "json")
	}
}

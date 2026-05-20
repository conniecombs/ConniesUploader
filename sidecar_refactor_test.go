// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import "testing"

func TestClampSidecarWorkers(t *testing.T) {
	tests := []struct {
		name string
		in   int
		want int
	}{
		{"below minimum", 0, minSidecarWorkers},
		{"minimum", minSidecarWorkers, minSidecarWorkers},
		{"middle", 8, 8},
		{"maximum", maxSidecarWorkers, maxSidecarWorkers},
		{"above maximum", 100, maxSidecarWorkers},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := clampSidecarWorkers(tt.in); got != tt.want {
				t.Fatalf("clampSidecarWorkers(%d) = %d, want %d", tt.in, got, tt.want)
			}
		})
	}
}

func TestWorkerLimitClamps(t *testing.T) {
	tests := []struct {
		name   string
		config map[string]string
		want   int
	}{
		{"nil config", nil, defaultUploadWorkers},
		{"missing threads", map[string]string{}, defaultUploadWorkers},
		{"invalid threads", map[string]string{"threads": "abc"}, defaultUploadWorkers},
		{"zero threads", map[string]string{"threads": "0"}, defaultUploadWorkers},
		{"valid threads", map[string]string{"threads": "4"}, 4},
		{"above maximum", map[string]string{"threads": "100"}, maxUploadWorkers},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := workerLimit(tt.config); got != tt.want {
				t.Fatalf("workerLimit(%v) = %d, want %d", tt.config, got, tt.want)
			}
		})
	}
}

func TestThumbnailWidthClamps(t *testing.T) {
	tests := []struct {
		name   string
		config map[string]string
		want   int
	}{
		{"nil config", nil, defaultThumbWidth},
		{"invalid width", map[string]string{"width": "abc"}, defaultThumbWidth},
		{"negative width", map[string]string{"width": "-1"}, defaultThumbWidth},
		{"minimum width", map[string]string{"width": "1"}, minThumbWidth},
		{"valid width", map[string]string{"width": "256"}, 256},
		{"above maximum", map[string]string{"width": "999"}, maxThumbWidth},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := thumbnailWidth(tt.config); got != tt.want {
				t.Fatalf("thumbnailWidth(%v) = %d, want %d", tt.config, got, tt.want)
			}
		})
	}
}

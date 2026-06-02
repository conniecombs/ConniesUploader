// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package core

import "time"

const DefaultUserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

func GetUserAgent(config map[string]string) string {
	if ua, ok := config["user_agent"]; ok && ua != "" {
		return ua
	}
	return DefaultUserAgent
}

const (
	ClientTimeout           = 180 * time.Second
	PreRequestTimeout       = 60 * time.Second
	ResponseHeaderTimeout   = 60 * time.Second
	PreRequestHeaderTimeout = 30 * time.Second
	ProgressReportInterval  = 2 * time.Second
)

const (
	DefaultMaxRetries        = 3
	DefaultInitialBackoff    = 1 * time.Second
	DefaultMaxBackoff        = 30 * time.Second
	DefaultBackoffMultiplier = 2.0
)

type JobRequest struct {
	ID          string            `json:"id,omitempty"`
	Action      string            `json:"action"`
	Service     string            `json:"service"`
	Files       []string          `json:"files"`
	Creds       map[string]string `json:"creds"`
	Config      map[string]string `json:"config"`
	ContextData map[string]string `json:"context_data"`
	HttpSpec    *HttpRequestSpec  `json:"http_spec,omitempty"`
	RateLimits  *RateLimitConfig  `json:"rate_limits,omitempty"`
	RetryConfig *RetryConfig      `json:"retry_config,omitempty"`
}

type RateLimitConfig struct {
	RequestsPerSecond float64 `json:"requests_per_second"`
	BurstSize         int     `json:"burst_size"`
	GlobalLimit       float64 `json:"global_limit"`
}

type HttpRequestSpec struct {
	URL             string                    `json:"url"`
	Method          string                    `json:"method"`
	Headers         map[string]string         `json:"headers"`
	MultipartFields map[string]MultipartField `json:"multipart_fields"`
	FormFields      map[string]string         `json:"form_fields,omitempty"`
	ResponseParser  ResponseParserSpec        `json:"response_parser"`
	PreRequest      *PreRequestSpec           `json:"pre_request,omitempty"`
}

type PreRequestSpec struct {
	Action          string            `json:"action"`
	URL             string            `json:"url"`
	Method          string            `json:"method"`
	Headers         map[string]string `json:"headers,omitempty"`
	FormFields      map[string]string `json:"form_fields,omitempty"`
	UseCookies      bool              `json:"use_cookies"`
	ExtractFields   map[string]string `json:"extract_fields"`
	ResponseType    string            `json:"response_type"`
	FollowUpRequest *PreRequestSpec   `json:"follow_up_request,omitempty"`
}

type MultipartField struct {
	Type  string `json:"type"`
	Value string `json:"value"`
}

type ResponseParserSpec struct {
	Type          string `json:"type"`
	URLPath       string `json:"url_path"`
	ThumbPath     string `json:"thumb_path"`
	StatusPath    string `json:"status_path"`
	SuccessValue  string `json:"success_value"`
	URLTemplate   string `json:"url_template,omitempty"`
	ThumbTemplate string `json:"thumb_template,omitempty"`
}

type OutputEvent struct {
	ID       string      `json:"id,omitempty"`
	Type     string      `json:"type"`
	FilePath string      `json:"file,omitempty"`
	Status   string      `json:"status,omitempty"`
	Url      string      `json:"url,omitempty"`
	Thumb    string      `json:"thumb,omitempty"`
	Msg      string      `json:"msg,omitempty"`
	Data     interface{} `json:"data,omitempty"`
}

type RetryConfig struct {
	MaxRetries         int           `json:"max_retries"`
	InitialBackoff     time.Duration `json:"initial_backoff"`
	MaxBackoff         time.Duration `json:"max_backoff"`
	BackoffMultiplier  float64       `json:"backoff_multiplier"`
	RetryableHTTPCodes []int         `json:"retryable_http_codes"`
}

type ProgressEvent struct {
	BytesTransferred int64   `json:"bytes_transferred"`
	TotalBytes       int64   `json:"total_bytes"`
	Speed            float64 `json:"speed"`
	Percentage       float64 `json:"percentage"`
	ETA              int     `json:"eta_seconds"`
}

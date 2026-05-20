// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import "github.com/conniecombs/GolangVersion/core"

// Package-level aliases keep the legacy root package API available for tests
// while the implementation lives in focused core and service packages.
type (
	JobRequest         = core.JobRequest
	HttpRequestSpec    = core.HttpRequestSpec
	PreRequestSpec     = core.PreRequestSpec
	MultipartField     = core.MultipartField
	ResponseParserSpec = core.ResponseParserSpec
	OutputEvent        = core.OutputEvent
	RetryConfig        = core.RetryConfig
	RateLimitConfig    = core.RateLimitConfig
	ProgressEvent      = core.ProgressEvent
	ProgressWriter     = core.ProgressWriter
)

const charset = core.Charset
const DefaultUserAgent = core.DefaultUserAgent

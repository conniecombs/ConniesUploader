// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"context"
	"io"
	"net/http"

	log "github.com/sirupsen/logrus"
	"golang.org/x/time/rate"

	"github.com/conniecombs/GolangVersion/core"
	"github.com/conniecombs/GolangVersion/services/imx"
)

func sendJSON(v interface{}) { core.SendJSON(v) }

func getRateLimiter(service string) *rate.Limiter { return core.GetRateLimiter(service) }

func updateRateLimiter(service string, cfg *core.RateLimitConfig) {
	core.UpdateRateLimiter(service, cfg)
}

func waitForRateLimit(ctx context.Context, service string) error {
	return core.WaitForRateLimit(ctx, service)
}

func getJSONValue(data map[string]interface{}, path string) string {
	return core.GetJSONValue(data, path)
}

func randomString(n int) string { return core.RandomString(n) }

func quoteEscape(s string) string { return core.QuoteEscape(s) }

func getImxSizeId(s string) string   { return imx.SizeID(s) }
func getImxFormatId(s string) string { return imx.FormatID(s) }

func getDefaultRetryConfig() *core.RetryConfig { return core.GetDefaultRetryConfig() }

func extractStatusCode(err error) int { return core.ExtractStatusCode(err) }

func retryWithBackoff[T any](
	ctx context.Context,
	config *core.RetryConfig,
	fn func() (T, int, error),
	logger *log.Entry,
) (T, error) {
	return core.RetryWithBackoff(ctx, config, fn, logger)
}

func NewProgressWriter(w io.Writer, totalBytes int64, filePath string) *core.ProgressWriter {
	return core.NewProgressWriter(w, totalBytes, filePath)
}

func doRequest(ctx context.Context, method, urlStr string, body io.Reader, contentType string) (*http.Response, error) {
	ensureInitialized()
	return core.DoRequest(ctx, client, method, urlStr, body, contentType)
}

func executeHttpUpload(ctx context.Context, fp string, job *JobRequest) (string, string, error) {
	ensureInitialized()
	return core.ExecuteHttpUpload(ctx, client, fp, job)
}

var (
	rateLimiters     = core.RateLimiters
	rateLimiterMutex = &core.RateLimiterMutex
)

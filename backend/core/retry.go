// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package core

import (
	"context"
	"crypto/rand"
	"fmt"
	"math"
	"regexp"
	"strconv"
	"strings"
	"time"

	log "github.com/sirupsen/logrus"
)

func GetDefaultRetryConfig() *RetryConfig {
	return &RetryConfig{
		MaxRetries:         DefaultMaxRetries,
		InitialBackoff:     DefaultInitialBackoff,
		MaxBackoff:         DefaultMaxBackoff,
		BackoffMultiplier:  DefaultBackoffMultiplier,
		RetryableHTTPCodes: []int{408, 429, 500, 502, 503, 504},
	}
}

func ExtractStatusCode(err error) int {
	if err == nil {
		return 0
	}
	errStr := err.Error()
	if idx := strings.Index(errStr, "status code"); idx != -1 {
		remaining := strings.TrimLeft(errStr[idx+len("status code"):], ": ")
		if fields := strings.Fields(remaining); len(fields) > 0 {
			if code, parseErr := strconv.Atoi(fields[0]); parseErr == nil {
				return code
			}
		}
	}
	if idx := strings.Index(strings.ToLower(errStr), "http "); idx != -1 {
		if fields := strings.Fields(errStr[idx+5:]); len(fields) > 0 {
			if code, parseErr := strconv.Atoi(fields[0]); parseErr == nil {
				return code
			}
		}
	}
	re := regexp.MustCompile(`\b([45]\d{2})\b`)
	if matches := re.FindStringSubmatch(errStr); len(matches) > 1 {
		if code, parseErr := strconv.Atoi(matches[1]); parseErr == nil {
			return code
		}
	}
	return 0
}

func IsRetryableError(err error, statusCode int, config *RetryConfig) bool {
	if err == nil {
		return false
	}
	for _, code := range config.RetryableHTTPCodes {
		if statusCode == code {
			return true
		}
	}
	errStr := strings.ToLower(err.Error())
	for _, pattern := range []string{
		"timeout", "connection refused", "connection reset", "temporary failure",
		"no such host", "network is unreachable", "broken pipe", "i/o timeout",
		"tls handshake timeout", "dial tcp", "eof",
	} {
		if strings.Contains(errStr, pattern) {
			return true
		}
	}
	return false
}

func CalculateBackoff(attempt int, config *RetryConfig) time.Duration {
	backoff := float64(config.InitialBackoff) * math.Pow(config.BackoffMultiplier, float64(attempt))
	if backoff > float64(config.MaxBackoff) {
		backoff = float64(config.MaxBackoff)
	}
	var jitterBytes [8]byte
	if _, err := rand.Read(jitterBytes[:]); err != nil {
		return time.Duration(backoff)
	}
	randUint := uint64(jitterBytes[0]) | uint64(jitterBytes[1])<<8 | uint64(jitterBytes[2])<<16 |
		uint64(jitterBytes[3])<<24 | uint64(jitterBytes[4])<<32 | uint64(jitterBytes[5])<<40 |
		uint64(jitterBytes[6])<<48 | uint64(jitterBytes[7])<<56
	jitter := (float64(randUint)/float64(^uint64(0)))*0.4 - 0.2
	return time.Duration(backoff * (1.0 + jitter))
}

func RetryWithBackoff[T any](
	ctx context.Context,
	config *RetryConfig,
	fn func() (T, int, error),
	logger *log.Entry,
) (T, error) {
	var lastErr error
	var lastStatusCode int
	var result T

	for attempt := 0; attempt <= config.MaxRetries; attempt++ {
		result, lastStatusCode, lastErr = fn()
		if lastErr == nil {
			if attempt > 0 {
				logger.WithField("attempt", attempt+1).Info("Request succeeded after retry")
			}
			return result, nil
		}
		if !IsRetryableError(lastErr, lastStatusCode, config) {
			return result, lastErr
		}
		if attempt >= config.MaxRetries {
			break
		}
		backoff := CalculateBackoff(attempt+1, config)
		logger.WithFields(log.Fields{"attempt": attempt + 1, "backoff": backoff.Seconds()}).Info("Request failed, retrying")
		select {
		case <-time.After(backoff):
		case <-ctx.Done():
			return result, ctx.Err()
		}
	}
	return result, fmt.Errorf("max retries (%d) exhausted, last error: %w", config.MaxRetries, lastErr)
}

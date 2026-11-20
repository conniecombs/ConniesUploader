// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package core

import (
	"context"
	"crypto/rand"
	"errors"
	"fmt"
	"io"
	"math"
	"net"
	"slices"
	"syscall"
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

// HTTPStatusError reports a response whose status code failed the request.
// Retry decisions read StatusCode only; Body is response text kept for the
// error message and is never inspected.
type HTTPStatusError struct {
	// Context names the step that got the response, e.g. "response follow-up".
	Context    string
	StatusCode int
	Body       string
}

func (e *HTTPStatusError) Error() string {
	msg := fmt.Sprintf("HTTP %d", e.StatusCode)
	if e.Context != "" {
		msg = e.Context + " " + msg
	}
	if e.Body != "" {
		msg += ": " + e.Body
	}
	return msg
}

// ExtractStatusCode returns the status code of an *HTTPStatusError in err's
// chain, or 0. Error text is never parsed.
func ExtractStatusCode(err error) int {
	var statusErr *HTTPStatusError
	if errors.As(err, &statusErr) {
		return statusErr.StatusCode
	}
	return 0
}

// noRetryError marks a failure that must not be retried automatically, such
// as an upload whose body reached the host but whose response was lost.
type noRetryError struct{ err error }

func (e *noRetryError) Error() string { return e.err.Error() }
func (e *noRetryError) Unwrap() error { return e.err }

// NoRetry wraps err so IsRetryableError reports false for it.
func NoRetry(err error) error {
	if err == nil {
		return nil
	}
	return &noRetryError{err: err}
}

// IsRetryableError reports whether a failed attempt may be repeated.
//
// statusCode is the status of the response the attempt received, or 0 when
// none arrived. Once a response arrived, only its status code decides:
// failures that come after it (parsing, a follow-up request) are not
// transport failures of this request and are never retried. Without a
// response the error is classified by type. Error text, which can quote a
// response body, is never inspected.
func IsRetryableError(err error, statusCode int, config *RetryConfig) bool {
	var noRetry *noRetryError
	if err == nil || errors.As(err, &noRetry) {
		return false
	}
	if statusCode == 0 {
		statusCode = ExtractStatusCode(err)
	}
	if statusCode != 0 {
		return slices.Contains(config.RetryableHTTPCodes, statusCode)
	}
	return isTransientTransportError(err)
}

// isTransientTransportError reports network failures worth another attempt:
// timeouts, connections that were refused, reset or closed early, and
// failed DNS lookups.
func isTransientTransportError(err error) bool {
	if errors.Is(err, context.Canceled) {
		return false
	}
	var netErr net.Error
	if errors.As(err, &netErr) && netErr.Timeout() {
		return true
	}
	if errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) {
		return true
	}
	var opErr *net.OpError
	if errors.As(err, &opErr) {
		return true
	}
	var dnsErr *net.DNSError
	if errors.As(err, &dnsErr) {
		return true
	}
	for _, errno := range []syscall.Errno{
		syscall.ECONNREFUSED, syscall.ECONNRESET, syscall.ECONNABORTED,
		syscall.EPIPE, syscall.ENETUNREACH, syscall.EHOSTUNREACH, syscall.ETIMEDOUT,
	} {
		if errors.Is(err, errno) {
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
		if !IsRetryableError(lastErr, lastStatusCode, config) || ctx.Err() != nil {
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

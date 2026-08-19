// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package core

import (
	"context"
	"fmt"
	"math"
	"sync"

	"golang.org/x/time/rate"
)

const (
	// Defaults are intentionally high so uploads behave like the legacy app
	// (full concurrent starts) unless Python attaches explicit lower limits.
	defaultServiceRequestsPerSecond = 100.0
	defaultServiceBurstSize         = 50
	defaultGlobalRequestsPerSecond  = 200.0
	defaultGlobalBurstSize          = 100
)

// RateLimiters and RateLimiterMutex are exported for test access. Host-specific
// limits belong in Python job specs; Go lazily creates generic defaults.
var RateLimiters = map[string]*rate.Limiter{}
var RateLimiterMutex sync.RWMutex
var globalRateLimiter = rate.NewLimiter(rate.Limit(defaultGlobalRequestsPerSecond), defaultGlobalBurstSize)

// disabledRateLimitServices tracks services whose proactive rate limiting was
// turned off via RateLimitConfig.RequestsPerSecond <= 0.
var disabledRateLimitServices = map[string]bool{}

func GetRateLimiter(service string) *rate.Limiter {
	RateLimiterMutex.RLock()
	if disabledRateLimitServices[service] {
		RateLimiterMutex.RUnlock()
		return nil
	}
	limiter, exists := RateLimiters[service]
	RateLimiterMutex.RUnlock()
	if !exists {
		limiter = rate.NewLimiter(
			rate.Limit(defaultServiceRequestsPerSecond),
			defaultServiceBurstSize,
		)
		RateLimiterMutex.Lock()
		// Re-check under write lock.
		if existing, ok := RateLimiters[service]; ok {
			limiter = existing
		} else if !disabledRateLimitServices[service] {
			RateLimiters[service] = limiter
		}
		RateLimiterMutex.Unlock()
	}
	return limiter
}

func UpdateRateLimiter(service string, config *RateLimitConfig) {
	if config == nil {
		return
	}
	RateLimiterMutex.Lock()
	defer RateLimiterMutex.Unlock()

	// RequestsPerSecond <= 0 disables proactive limiting for this service
	// (legacy-like full concurrency). Transient 429s still use retry backoff.
	if config.RequestsPerSecond <= 0 {
		disabledRateLimitServices[service] = true
		delete(RateLimiters, service)
		return
	}
	disabledRateLimitServices[service] = false

	burst := config.BurstSize
	if burst < 1 {
		burst = 1
	}
	limiter := RateLimiters[service]
	if limiter == nil {
		RateLimiters[service] = rate.NewLimiter(rate.Limit(config.RequestsPerSecond), burst)
	} else {
		limiter.SetLimit(rate.Limit(config.RequestsPerSecond))
		limiter.SetBurst(burst)
	}
	if config.GlobalLimit > 0 {
		globalRateLimiter.SetLimit(rate.Limit(config.GlobalLimit))
		if config.BurstSize > 0 {
			globalRateLimiter.SetBurst(config.BurstSize)
		}
	}
}

// JobHasExplicitRateLimit reports whether the job requested proactive throttling.
func JobHasExplicitRateLimit(job *JobRequest) bool {
	return job != nil && job.RateLimits != nil && job.RateLimits.RequestsPerSecond > 0
}

// WaitForRateLimit blocks until both the global and per-service limiters allow
// another request. Services with disabled / unlimited limiters return immediately.
func WaitForRateLimit(ctx context.Context, service string) error {
	RateLimiterMutex.RLock()
	disabled := disabledRateLimitServices[service]
	RateLimiterMutex.RUnlock()
	if disabled {
		return nil
	}

	if err := globalRateLimiter.Wait(ctx); err != nil {
		return fmt.Errorf("global rate limit wait cancelled: %w", err)
	}
	limiter := GetRateLimiter(service)
	if limiter == nil {
		return nil
	}
	// Inf limit means effectively unlimited.
	if limiter.Limit() == rate.Inf || math.IsInf(float64(limiter.Limit()), 1) {
		return nil
	}
	if err := limiter.Wait(ctx); err != nil {
		return fmt.Errorf("service rate limit wait cancelled: %w", err)
	}
	return nil
}

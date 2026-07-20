// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package core

import (
	"context"
	"fmt"
	"sync"

	"golang.org/x/time/rate"
)

const (
	defaultServiceRequestsPerSecond = 2.0
	defaultServiceBurstSize         = 5
)

// RateLimiters and RateLimiterMutex are exported for test access. Host-specific
// limits belong in Python job specs; Go lazily creates generic defaults.
var RateLimiters = map[string]*rate.Limiter{}
var RateLimiterMutex sync.RWMutex
var globalRateLimiter = rate.NewLimiter(rate.Limit(10.0), 20)

func GetRateLimiter(service string) *rate.Limiter {
	RateLimiterMutex.RLock()
	limiter, exists := RateLimiters[service]
	RateLimiterMutex.RUnlock()
	if !exists {
		limiter = rate.NewLimiter(
			rate.Limit(defaultServiceRequestsPerSecond),
			defaultServiceBurstSize,
		)
		RateLimiterMutex.Lock()
		RateLimiters[service] = limiter
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
	limiter := RateLimiters[service]
	if limiter == nil {
		RateLimiters[service] = rate.NewLimiter(rate.Limit(config.RequestsPerSecond), config.BurstSize)
	} else {
		limiter.SetLimit(rate.Limit(config.RequestsPerSecond))
		limiter.SetBurst(config.BurstSize)
	}
	if config.GlobalLimit > 0 {
		globalRateLimiter.SetLimit(rate.Limit(config.GlobalLimit))
	}
}

func WaitForRateLimit(ctx context.Context, service string) error {
	if err := globalRateLimiter.Wait(ctx); err != nil {
		return fmt.Errorf("global rate limit wait cancelled: %w", err)
	}
	if err := GetRateLimiter(service).Wait(ctx); err != nil {
		return fmt.Errorf("service rate limit wait cancelled: %w", err)
	}
	return nil
}

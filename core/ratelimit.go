// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package core

import (
	"context"
	"fmt"
	"sync"

	"golang.org/x/time/rate"
)

// RateLimiters and RateLimiterMutex are exported for test access.
var RateLimiters = map[string]*rate.Limiter{
	"imx.to":         rate.NewLimiter(rate.Limit(2.0), 5),
	"pixhost.to":     rate.NewLimiter(rate.Limit(2.0), 5),
	"vipr.im":        rate.NewLimiter(rate.Limit(2.0), 5),
	"turboimagehost": rate.NewLimiter(rate.Limit(2.0), 5),
	"imagebam.com":   rate.NewLimiter(rate.Limit(2.0), 5),
	"vipergirls.to":  rate.NewLimiter(rate.Limit(1.0), 3),
}
var RateLimiterMutex sync.RWMutex
var globalRateLimiter = rate.NewLimiter(rate.Limit(10.0), 20)

func GetRateLimiter(service string) *rate.Limiter {
	RateLimiterMutex.RLock()
	limiter, exists := RateLimiters[service]
	RateLimiterMutex.RUnlock()
	if !exists {
		limiter = rate.NewLimiter(rate.Limit(2.0), 5)
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
	RateLimiters[service] = rate.NewLimiter(rate.Limit(config.RequestsPerSecond), config.BurstSize)
	if config.GlobalLimit > 0 {
		oldBurst := globalRateLimiter.Burst()
		globalRateLimiter = rate.NewLimiter(rate.Limit(config.GlobalLimit), oldBurst)
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

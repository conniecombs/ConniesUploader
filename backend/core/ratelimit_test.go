package core

import (
	"context"
	"testing"
	"time"

	"golang.org/x/time/rate"
)

func TestUpdateRateLimiterKeepsExistingLimiter(t *testing.T) {
	service := "imagebam.test"
	RateLimiterMutex.Lock()
	previousLimiters := RateLimiters
	previousDisabled := disabledRateLimitServices
	RateLimiters = map[string]*rate.Limiter{}
	disabledRateLimitServices = map[string]bool{}
	RateLimiterMutex.Unlock()
	defer func() {
		RateLimiterMutex.Lock()
		RateLimiters = previousLimiters
		disabledRateLimitServices = previousDisabled
		RateLimiterMutex.Unlock()
	}()

	UpdateRateLimiter(service, &RateLimitConfig{RequestsPerSecond: 2, BurstSize: 5})
	first := GetRateLimiter(service)

	UpdateRateLimiter(service, &RateLimitConfig{RequestsPerSecond: 1, BurstSize: 1})
	second := GetRateLimiter(service)

	if second != first {
		t.Fatal("UpdateRateLimiter replaced the existing limiter")
	}
	if got := second.Limit(); got != 1 {
		t.Fatalf("limit = %v, want 1", got)
	}
	if got := second.Burst(); got != 1 {
		t.Fatalf("burst = %d, want 1", got)
	}
}

func TestUpdateRateLimiterZeroDisablesProactiveLimit(t *testing.T) {
	service := "disable.rate.limit.test"
	RateLimiterMutex.Lock()
	previousLimiters := RateLimiters
	previousDisabled := disabledRateLimitServices
	RateLimiters = map[string]*rate.Limiter{}
	disabledRateLimitServices = map[string]bool{}
	RateLimiterMutex.Unlock()
	defer func() {
		RateLimiterMutex.Lock()
		RateLimiters = previousLimiters
		disabledRateLimitServices = previousDisabled
		RateLimiterMutex.Unlock()
	}()

	UpdateRateLimiter(service, &RateLimitConfig{RequestsPerSecond: 0, BurstSize: 1})
	if GetRateLimiter(service) != nil {
		t.Fatal("expected nil limiter when RPS <= 0")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	if err := WaitForRateLimit(ctx, service); err != nil {
		t.Fatalf("disabled rate limit should not wait: %v", err)
	}
}

func TestJobHasExplicitRateLimit(t *testing.T) {
	if JobHasExplicitRateLimit(nil) {
		t.Fatal("nil job should not have explicit rate limit")
	}
	if JobHasExplicitRateLimit(&JobRequest{}) {
		t.Fatal("job without rate_limits should not throttle")
	}
	if JobHasExplicitRateLimit(&JobRequest{RateLimits: &RateLimitConfig{RequestsPerSecond: 0}}) {
		t.Fatal("RPS <= 0 should not throttle")
	}
	if !JobHasExplicitRateLimit(&JobRequest{RateLimits: &RateLimitConfig{RequestsPerSecond: 2}}) {
		t.Fatal("positive RPS should throttle")
	}
}

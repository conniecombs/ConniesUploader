package core

import (
	"testing"

	"golang.org/x/time/rate"
)

func TestUpdateRateLimiterKeepsExistingLimiter(t *testing.T) {
	service := "imagebam.test"
	RateLimiterMutex.Lock()
	previousLimiters := RateLimiters
	RateLimiters = map[string]*rate.Limiter{}
	RateLimiterMutex.Unlock()
	defer func() {
		RateLimiterMutex.Lock()
		RateLimiters = previousLimiters
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

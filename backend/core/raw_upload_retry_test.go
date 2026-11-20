// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"sync/atomic"
	"testing"
	"time"
)

// statusHost answers each upload with the next status of its script (the
// last one repeats), with a Retry-After header when given.
type statusHost struct {
	hits       int32
	script     []int
	retryAfter string
	server     *httptest.Server
}

func newStatusHost(t *testing.T, retryAfter string, script ...int) *statusHost {
	t.Helper()
	h := &statusHost{script: script, retryAfter: retryAfter}
	h.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		n := int(atomic.AddInt32(&h.hits, 1))
		status := h.script[min(n, len(h.script))-1]
		if status != http.StatusOK && h.retryAfter != "" {
			w.Header().Set("Retry-After", h.retryAfter)
		}
		w.WriteHeader(status)
		_, _ = w.Write([]byte(`{"answer":` + strconv.Itoa(n) + `}`))
	}))
	t.Cleanup(h.server.Close)
	return h
}

func setRetryAfterCap(t *testing.T, cap time.Duration) {
	t.Helper()
	old := RawRetryAfterCap
	RawRetryAfterCap = cap
	t.Cleanup(func() { RawRetryAfterCap = old })
}

// 429 and 503 mean the host did not take the file, so the upload is sent
// again before Python sees an answer.
func TestRawUploadRetries429And503BeforeAnswering(t *testing.T) {
	for _, status := range []int{http.StatusTooManyRequests, http.StatusServiceUnavailable} {
		fp := writeUploadFile(t, 512)
		host := newStatusHost(t, "0", status, status, http.StatusOK)
		result, err := ExecuteRawUpload(context.Background(), host.server.Client(), fp,
			rawJob(fp, rawRequest(host.server.URL, fp), fastRetries()))
		if err != nil {
			t.Fatalf("%d: %v", status, err)
		}
		if result.StatusCode != http.StatusOK || result.Body != `{"answer":3}` {
			t.Fatalf("%d: result = %+v, want the third answer", status, result)
		}
		if got := atomic.LoadInt32(&host.hits); got != 3 {
			t.Fatalf("%d: host received %d uploads, want 3", status, got)
		}
	}
}

// After the legacy path's attempt count the last refusal goes to Python,
// which reports it with the host's message.
func TestRawUploadGivesUpAfterTheLegacyAttemptCount(t *testing.T) {
	fp := writeUploadFile(t, 512)
	host := newStatusHost(t, "", http.StatusTooManyRequests)
	retries := fastRetries()
	result, err := ExecuteRawUpload(context.Background(), host.server.Client(), fp,
		rawJob(fp, rawRequest(host.server.URL, fp), retries))
	if err != nil {
		t.Fatalf("raw upload: %v", err)
	}
	if result.StatusCode != http.StatusTooManyRequests {
		t.Fatalf("result = %+v, want the last 429 answer", result)
	}
	if got, want := atomic.LoadInt32(&host.hits), int32(retries.MaxRetries+1); got != want {
		t.Fatalf("host received %d uploads, want %d", got, want)
	}

	noRetries := fastRetries()
	noRetries.MaxRetries = 0
	once := newStatusHost(t, "", http.StatusServiceUnavailable)
	if _, err := ExecuteRawUpload(context.Background(), once.server.Client(), fp,
		rawJob(fp, rawRequest(once.server.URL, fp), noRetries)); err != nil {
		t.Fatal(err)
	}
	if got := atomic.LoadInt32(&once.hits); got != 1 {
		t.Fatalf("max_retries 0: host received %d uploads, want 1", got)
	}
}

// The host may already have stored the file after these answers, so it is
// never sent again.
func TestRawUploadIsNotResentAfterOtherServerErrors(t *testing.T) {
	for _, status := range []int{500, 502, 504, 520, 522, 524, 408} {
		fp := writeUploadFile(t, 512)
		host := newStatusHost(t, "0", status, http.StatusOK)
		result, err := ExecuteRawUpload(context.Background(), host.server.Client(), fp,
			rawJob(fp, rawRequest(host.server.URL, fp), fastRetries()))
		if err != nil || result.StatusCode != status {
			t.Fatalf("%d: result=%+v err=%v, want the first answer", status, result, err)
		}
		if got := atomic.LoadInt32(&host.hits); got != 1 {
			t.Fatalf("%d: host received %d uploads, want 1", status, got)
		}
	}
}

// An answer cut off while it is read still means the host answered: the
// upload is not sent again.
func TestRawUploadIsNotResentWhenTheAnswerIsCutOff(t *testing.T) {
	fp := writeUploadFile(t, 512)
	var hits int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		atomic.AddInt32(&hits, 1)
		w.Header().Set("Content-Length", "100")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"partial"`))
		if flusher, ok := w.(http.Flusher); ok {
			flusher.Flush()
		}
		if conn, _, err := w.(http.Hijacker).Hijack(); err == nil {
			_ = conn.Close()
		}
	}))
	defer server.Close()
	_, err := ExecuteRawUpload(context.Background(), server.Client(), fp, rawJob(fp, rawRequest(server.URL, fp), fastRetries()))
	if err == nil {
		t.Fatal("a cut-off answer was returned as complete")
	}
	if got := atomic.LoadInt32(&hits); got != 1 {
		t.Fatalf("host received %d uploads, want 1", got)
	}
}

// Only the 429/503 subset of the job's retryable codes is retried.
func TestRawUploadRetriesOnlyCodesTheJobAllows(t *testing.T) {
	fp := writeUploadFile(t, 512)
	host := newStatusHost(t, "0", http.StatusServiceUnavailable, http.StatusOK)
	retries := fastRetries()
	retries.RetryableHTTPCodes = []int{http.StatusTooManyRequests}
	result, err := ExecuteRawUpload(context.Background(), host.server.Client(), fp,
		rawJob(fp, rawRequest(host.server.URL, fp), retries))
	if err != nil || result.StatusCode != http.StatusServiceUnavailable || atomic.LoadInt32(&host.hits) != 1 {
		t.Fatalf("result=%+v err=%v hits=%d, want one 503 answer", result, err, host.hits)
	}
}

func TestRawUploadHonoursRetryAfterUpToTheCap(t *testing.T) {
	fp := writeUploadFile(t, 512)
	host := newStatusHost(t, "1", http.StatusServiceUnavailable, http.StatusOK)
	start := time.Now()
	if _, err := ExecuteRawUpload(context.Background(), host.server.Client(), fp,
		rawJob(fp, rawRequest(host.server.URL, fp), fastRetries())); err != nil {
		t.Fatal(err)
	}
	if elapsed := time.Since(start); elapsed < 900*time.Millisecond {
		t.Fatalf("retried after %v, want the host's Retry-After of 1s", elapsed)
	}

	setRetryAfterCap(t, 150*time.Millisecond)
	for _, header := range []string{"3600", time.Now().Add(time.Hour).UTC().Format(http.TimeFormat)} {
		capped := newStatusHost(t, header, http.StatusTooManyRequests, http.StatusOK)
		start = time.Now()
		result, err := ExecuteRawUpload(context.Background(), capped.server.Client(), fp,
			rawJob(fp, rawRequest(capped.server.URL, fp), fastRetries()))
		if err != nil || result.StatusCode != http.StatusOK {
			t.Fatalf("Retry-After %q: result=%+v err=%v", header, result, err)
		}
		if elapsed := time.Since(start); elapsed > 3*time.Second {
			t.Fatalf("Retry-After %q waited %v, want the cap", header, elapsed)
		}
	}
}

// A Retry-After too large for a time.Duration is the cap, not a wrapped
// value: 9999999999 seconds once overflowed to "send again at once".
func TestRetryAfterSecondsBeyondTheDurationRangeAreCapped(t *testing.T) {
	for _, header := range []string{"61", "3600", "9999999999", "99999999999999", "9223372036854775807", "99999999999999999999"} {
		if wait, ok := retryAfter(header); !ok || wait != RawRetryAfterCap {
			t.Errorf("Retry-After %s = %v (ok=%v), want the cap %v", header, wait, ok, RawRetryAfterCap)
		}
	}
	for _, header := range []string{"0", "-1", "-9999999999", "-9223372036854775808", "-99999999999999999999"} {
		if wait, ok := retryAfter(header); !ok || wait != 0 {
			t.Errorf("Retry-After %s = %v (ok=%v), want 0", header, wait, ok)
		}
	}
	if wait, ok := retryAfter("60"); !ok || wait != 60*time.Second {
		t.Errorf("Retry-After 60 = %v (ok=%v), want 60s", wait, ok)
	}
	if wait, ok := retryAfter(" 2 "); !ok || wait != 2*time.Second {
		t.Errorf("Retry-After 2 = %v (ok=%v), want 2s", wait, ok)
	}

	setRetryAfterCap(t, 150*time.Millisecond)
	if wait, _ := retryAfter("9999999999"); wait != 150*time.Millisecond {
		t.Errorf("with a 150ms cap, Retry-After 9999999999 = %v", wait)
	}
	if wait, _ := retryAfter("0"); wait != 0 {
		t.Errorf("with a 150ms cap, Retry-After 0 = %v", wait)
	}
}

func TestRawUploadStopsRetryingWhenCancelled(t *testing.T) {
	fp := writeUploadFile(t, 512)
	host := newStatusHost(t, "30", http.StatusServiceUnavailable)
	ctx, cancel := context.WithCancel(context.Background())
	time.AfterFunc(100*time.Millisecond, cancel)
	start := time.Now()
	_, err := ExecuteRawUpload(ctx, host.server.Client(), fp, rawJob(fp, rawRequest(host.server.URL, fp), fastRetries()))
	if err == nil {
		t.Fatal("a cancelled upload returned an answer")
	}
	if elapsed := time.Since(start); elapsed > 3*time.Second {
		t.Fatalf("cancel took %v to stop the retry wait", elapsed)
	}
	if got := atomic.LoadInt32(&host.hits); got != 1 {
		t.Fatalf("host received %d uploads after the cancel, want 1", got)
	}
}

// A retry waits for the host's rate limit like the first attempt does.
func TestRawUploadRetryWaitsForTheRateLimit(t *testing.T) {
	fp := writeUploadFile(t, 512)
	host := newStatusHost(t, "0", http.StatusTooManyRequests, http.StatusTooManyRequests, http.StatusOK)
	job := rawJob(fp, rawRequest(host.server.URL, fp), fastRetries())
	job.Service = "raw-retry-rate.test"
	job.RateLimits = &RateLimitConfig{RequestsPerSecond: 4, BurstSize: 1}
	UpdateRateLimiter(job.Service, job.RateLimits)
	start := time.Now()
	if _, err := ExecuteRawUpload(context.Background(), host.server.Client(), fp, job); err != nil {
		t.Fatal(err)
	}
	// Three sends at 4 per second with a burst of 1: at least two waits of 250 ms.
	if elapsed := time.Since(start); elapsed < 450*time.Millisecond {
		t.Fatalf("three sends took %v, faster than the rate limit allows", elapsed)
	}
}

// A refusal that was retried says nothing about the host keeping the file.
func TestRetriedRefusalsDoNotCountAsBodiesTheHostKept(t *testing.T) {
	fp := writeUploadFile(t, 4096)
	var hits int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		if atomic.AddInt32(&hits, 1) == 1 {
			w.Header().Set("Retry-After", "0")
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		if conn, _, err := w.(http.Hijacker).Hijack(); err == nil {
			_ = conn.Close()
		}
	}))
	defer server.Close()
	_, err := ExecuteRawUpload(context.Background(), server.Client(), fp, rawJob(fp, rawRequest(server.URL, fp), fastRetries()))
	if err == nil || !UploadBodySent(err) {
		t.Fatalf("err = %v, want a lost answer whose body reached the host", err)
	}

	// Refused with 503, then cancelled while waiting to retry.
	refused := newStatusHost(t, "30", http.StatusServiceUnavailable)
	ctx, cancel := context.WithCancel(context.Background())
	time.AfterFunc(100*time.Millisecond, cancel)
	_, err = ExecuteRawUpload(ctx, refused.server.Client(), fp, rawJob(fp, rawRequest(refused.server.URL, fp), fastRetries()))
	if err == nil || UploadBodySent(err) {
		t.Fatalf("err = %v: a refusal must not count as a body the host kept", err)
	}
}

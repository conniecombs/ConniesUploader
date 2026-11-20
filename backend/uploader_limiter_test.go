// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package main

import (
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

// gateHost holds every upload until the test releases it, so concurrency can
// be observed step by step.
type gateHost struct {
	mu       sync.Mutex
	inFlight map[string]int // by request path
	peak     int
	release  chan struct{}
	server   *httptest.Server
}

func newGateHost(t *testing.T) *gateHost {
	t.Helper()
	g := &gateHost{inFlight: map[string]int{}, release: make(chan struct{})}
	g.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		g.mu.Lock()
		g.inFlight[r.URL.Path]++
		if total := g.totalLocked(); total > g.peak {
			g.peak = total
		}
		g.mu.Unlock()
		select {
		case <-g.release:
		case <-r.Context().Done():
		}
		g.mu.Lock()
		g.inFlight[r.URL.Path]--
		g.mu.Unlock()
		_, _ = w.Write([]byte(`{"data":{"image_url":"u","thumbnail_url":"t"}}`))
	}))
	t.Cleanup(g.server.Close)
	return g
}

func (g *gateHost) totalLocked() int {
	total := 0
	for _, n := range g.inFlight {
		total += n
	}
	return total
}

func (g *gateHost) counts() (total int, byPath map[string]int, peak int) {
	g.mu.Lock()
	defer g.mu.Unlock()
	byPath = make(map[string]int, len(g.inFlight))
	for path, n := range g.inFlight {
		byPath[path] = n
	}
	return g.totalLocked(), byPath, g.peak
}

// waitInFlight waits until want uploads are held, then gives late starters a
// moment to show up so the count is stable.
func (g *gateHost) waitInFlight(t *testing.T, want int) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if total, _, _ := g.counts(); total == want {
			time.Sleep(50 * time.Millisecond)
			if total, _, _ := g.counts(); total == want {
				return
			}
		}
		time.Sleep(5 * time.Millisecond)
	}
	total, byPath, _ := g.counts()
	t.Fatalf("uploads in flight = %d %v, want %d", total, byPath, want)
}

func limiterJob(t *testing.T, serverURL, service, path string, files, threads int) JobRequest {
	t.Helper()
	dir := t.TempDir()
	paths := make([]string, files)
	for i := range paths {
		paths[i] = filepath.Join(dir, fmt.Sprintf("img%02d.jpg", i))
		if err := os.WriteFile(paths[i], []byte("jpeg-bytes"), 0o600); err != nil {
			t.Fatalf("write: %v", err)
		}
	}
	return JobRequest{
		ID:      "job" + strings.ReplaceAll(path, "/", "-"),
		Action:  "http_upload",
		Service: service,
		Files:   paths,
		Config:  map[string]string{"threads": strconv.Itoa(threads)},
		HttpSpec: &HttpRequestSpec{
			URL:             serverURL + path,
			Method:          http.MethodPost,
			MultipartFields: map[string]MultipartField{"image": {Type: "file", Value: ""}},
			ResponseParser:  ResponseParserSpec{Type: "json", URLPath: "data.image_url", ThumbPath: "data.thumbnail_url"},
		},
		RetryConfig: &RetryConfig{MaxRetries: 0},
	}
}

func runJobsWithGate(t *testing.T, g *gateHost, steps func(start func(JobRequest))) []OutputEvent {
	t.Helper()
	oldClient := client
	client = g.server.Client()
	defer func() { client = oldClient }()

	var wg sync.WaitGroup
	start := func(job JobRequest) {
		wg.Add(1)
		go func() {
			defer wg.Done()
			handleJob(job)
		}()
	}
	return captureSidecarEvents(t, func() {
		defer wg.Wait()
		defer close(g.release)
		steps(start)
	})
}

// A one-file job started while a big job runs must not shrink the host's
// concurrency to one.
func TestSmallJobDoesNotThrottleOtherJobsOnSameService(t *testing.T) {
	g := newGateHost(t)
	big := limiterJob(t, g.server.URL, "limiter-small.test", "/big", 6, 3)
	small := limiterJob(t, g.server.URL, "limiter-small.test", "/small", 1, 3)

	events := runJobsWithGate(t, g, func(start func(JobRequest)) {
		start(big)
		g.waitInFlight(t, 3)
		start(small)
		time.Sleep(50 * time.Millisecond)
		g.release <- struct{}{}
		g.release <- struct{}{}
		// Two slots freed under a Thread Limit of 3: two more uploads start.
		g.waitInFlight(t, 3)
	})
	if got := len(eventsOfType(events, "result")); got != 7 {
		t.Fatalf("results = %d, want 7", got)
	}
}

// Jobs with different Thread Limits on one service: a job starts a file only
// while the service has fewer uploads running than its own limit, so the
// total never exceeds the largest limit and a later, lower limit does not cut
// the earlier job's concurrency.
func TestJobsWithDifferentThreadLimitsShareServiceSlots(t *testing.T) {
	g := newGateHost(t)
	wide := limiterJob(t, g.server.URL, "limiter-mixed.test", "/wide", 6, 4)
	narrow := limiterJob(t, g.server.URL, "limiter-mixed.test", "/narrow", 2, 2)

	events := runJobsWithGate(t, g, func(start func(JobRequest)) {
		start(wide)
		g.waitInFlight(t, 4)
		start(narrow)
		time.Sleep(50 * time.Millisecond)
		g.release <- struct{}{}
		// 3 running: below the wide job's limit, not below the narrow one's.
		g.waitInFlight(t, 4)
		if _, byPath, _ := g.counts(); byPath["/narrow"] != 0 {
			t.Errorf("narrow job started %d upload(s) while 3 were running, want 0", byPath["/narrow"])
		}
	})
	if _, _, peak := g.counts(); peak > 4 {
		t.Fatalf("peak concurrency = %d, want at most 4", peak)
	}
	if got := len(eventsOfType(events, "result")); got != 8 {
		t.Fatalf("results = %d, want 8", got)
	}
}

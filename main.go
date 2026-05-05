// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/http/cookiejar"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	log "github.com/sirupsen/logrus"
	"golang.org/x/time/rate"

	"github.com/conniecombs/GolangVersion/core"
	"github.com/conniecombs/GolangVersion/services"
	"github.com/conniecombs/GolangVersion/services/imagebam"
	"github.com/conniecombs/GolangVersion/services/imx"
	"github.com/conniecombs/GolangVersion/services/pixhost"
	"github.com/conniecombs/GolangVersion/services/turbo"
	"github.com/conniecombs/GolangVersion/services/vipr"
	"github.com/conniecombs/GolangVersion/services/vipergirls"
)

const (
	minSidecarWorkers = 1
	maxSidecarWorkers = 16
)

// ---------------------------------------------------------------------------
// Package-level types — aliased from core so existing test files compile
// unchanged.
// ---------------------------------------------------------------------------

type (
	JobRequest         = core.JobRequest
	HttpRequestSpec    = core.HttpRequestSpec
	PreRequestSpec     = core.PreRequestSpec
	MultipartField     = core.MultipartField
	ResponseParserSpec = core.ResponseParserSpec
	OutputEvent        = core.OutputEvent
	RetryConfig        = core.RetryConfig
	RateLimitConfig    = core.RateLimitConfig
	ProgressEvent      = core.ProgressEvent
	ProgressWriter     = core.ProgressWriter
)

// Constant aliases so test files referencing old names continue to compile.
const charset = core.Charset
const DefaultUserAgent = core.DefaultUserAgent

// ---------------------------------------------------------------------------
// Shared HTTP client (package-level so test files can replace it).
// ---------------------------------------------------------------------------

var client *http.Client

// registry holds all registered service modules.
var registry *services.Registry

func clampSidecarWorkers(workers int) int {
	if workers < minSidecarWorkers {
		return minSidecarWorkers
	}
	if workers > maxSidecarWorkers {
		return maxSidecarWorkers
	}
	return workers
}

func initHTTPClient() {
	jar, err := cookiejar.New(nil)
	if err != nil {
		log.WithError(err).Warn("failed to initialize cookie jar; continuing without persistent cookies")
	}
	client = &http.Client{
		Timeout: core.ClientTimeout,
		Jar:     jar,
		Transport: &http.Transport{
			MaxIdleConns:          100,
			MaxIdleConnsPerHost:   10,
			MaxConnsPerHost:       20,
			IdleConnTimeout:       90 * time.Second,
			ResponseHeaderTimeout: core.ResponseHeaderTimeout,
			ForceAttemptHTTP2:     true,
		},
	}
	initRegistry()
}

func initRegistry() {
	registry = services.NewRegistry()
	registry.Register(imx.New(client))
	registry.Register(pixhost.New(client))
	registry.Register(vipr.New(client))
	registry.Register(turbo.New(client))
	registry.Register(imagebam.New(client))
	registry.Register(vipergirls.New(client))
}

// ensureInitialized lazily bootstraps the HTTP client and service registry.
// Called by wrapper functions so tests that set client directly still work.
func ensureInitialized() {
	if client == nil || registry == nil {
		initHTTPClient()
	}
}

// ---------------------------------------------------------------------------
// Thin wrapper functions so test files referencing the old monolith names
// continue to compile without modification.
// ---------------------------------------------------------------------------

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

func getImxSizeId(s string) string  { return imx.SizeID(s) }
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

// doRequest wraps core.DoRequest using the package-level client.
func doRequest(ctx context.Context, method, urlStr string, body io.Reader, contentType string) (*http.Response, error) {
	return core.DoRequest(ctx, client, method, urlStr, body, contentType)
}

// executeHttpUpload wraps core.ExecuteHttpUpload using the package-level client.
func executeHttpUpload(ctx context.Context, fp string, job *JobRequest) (string, string, error) {
	return core.ExecuteHttpUpload(ctx, client, fp, job)
}

// ---------------------------------------------------------------------------
// Backward-compat wrappers for service-specific functions referenced by tests.
// ---------------------------------------------------------------------------

func createPixhostGallery(name string) (map[string]string, error) {
	ensureInitialized()
	svc, ok := registry.Get(pixhost.ServiceID)
	if !ok {
		return nil, fmt.Errorf("pixhost module not registered")
	}
	creator, ok := svc.(services.GalleryCreator)
	if !ok {
		return nil, fmt.Errorf("pixhost does not implement GalleryCreator")
	}
	_, data, err := creator.CreateGallery(nil, name)
	if err != nil {
		return nil, err
	}
	if m, ok := data.(map[string]string); ok {
		return m, nil
	}
	return nil, fmt.Errorf("unexpected data type from pixhost.CreateGallery")
}

func createImxGallery(creds map[string]string, name string) (string, error) {
	ensureInitialized()
	svc, ok := registry.Get(imx.ServiceID)
	if !ok {
		return "", fmt.Errorf("imx module not registered")
	}
	creator, ok := svc.(services.GalleryCreator)
	if !ok {
		return "", fmt.Errorf("imx does not implement GalleryCreator")
	}
	id, _, err := creator.CreateGallery(creds, name)
	return id, err
}

func createViprGallery(name string) (string, error) {
	ensureInitialized()
	svc, ok := registry.Get(vipr.ServiceID)
	if !ok {
		return "", fmt.Errorf("vipr module not registered")
	}
	creator, ok := svc.(services.GalleryCreator)
	if !ok {
		return "", fmt.Errorf("vipr does not implement GalleryCreator")
	}
	id, _, err := creator.CreateGallery(nil, name)
	return id, err
}

// rateLimiters and rateLimiterMutex mirror core's exported vars so stress
// tests that reference them by name continue to compile.
var (
	rateLimiters    = core.RateLimiters
	rateLimiterMutex = &core.RateLimiterMutex
)

// ---------------------------------------------------------------------------
// Logger init
// ---------------------------------------------------------------------------

func init() {
	log.SetFormatter(&log.JSONFormatter{
		TimestampFormat: "2006-01-02 15:04:05",
		FieldMap: log.FieldMap{
			log.FieldKeyTime:  "timestamp",
			log.FieldKeyLevel: "level",
			log.FieldKeyMsg:   "message",
		},
	})
	log.SetOutput(os.Stderr)
	log.SetLevel(log.InfoLevel)
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

func main() {
	workerCount := flag.Int("workers", 8, "Number of worker goroutines")
	flag.Parse()
	clampedWorkerCount := clampSidecarWorkers(*workerCount)
	if clampedWorkerCount != *workerCount {
		log.WithFields(log.Fields{
			"requested": *workerCount,
			"effective":  clampedWorkerCount,
		}).Warn("sidecar worker count clamped")
	}

	log.WithField("workers", clampedWorkerCount).Info("Go sidecar starting")
	core.SendJSON(OutputEvent{Type: "log", Msg: fmt.Sprintf("=== GO SIDECAR STARTED - WORKERS: %d ===", clampedWorkerCount)})

	initHTTPClient()
	initRegistry()

	jobQueue := make(chan JobRequest, 100)
	var wg sync.WaitGroup
	shutdownChan := make(chan struct{})

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	for i := 0; i < clampedWorkerCount; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for job := range jobQueue {
				handleJob(job)
			}
		}()
	}

	go func() {
		<-sigChan
		close(shutdownChan)
	}()

	decoder := json.NewDecoder(os.Stdin)
	for {
		select {
		case <-shutdownChan:
			goto shutdown
		default:
			var job JobRequest
			if err := decoder.Decode(&job); err != nil {
				if err == io.EOF {
					close(shutdownChan)
					goto shutdown
				}
				core.SendJSON(OutputEvent{Type: "error", Msg: fmt.Sprintf("JSON decode error: %v", err)})
				continue
			}
			jobQueue <- job
		}
	}

shutdown:
	close(jobQueue)
	wg.Wait()
	core.SendJSON(OutputEvent{Type: "log", Msg: "=== GO SIDECAR SHUTDOWN COMPLETE ==="})
}

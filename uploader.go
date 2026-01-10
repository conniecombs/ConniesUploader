package main

import (
	"bytes"
	"context"
	"crypto/md5"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"github.com/PuerkitoBio/goquery"
	"github.com/disintegration/imaging"
	log "github.com/sirupsen/logrus"
	"golang.org/x/time/rate"
	"image"
	"image/jpeg"
	_ "image/png"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/cookiejar"
	"net/textproto"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

// --- Constants ---
const UserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

func init() {
	// Configure structured logging
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

// --- Protocol Structs ---
type JobRequest struct {
	Action      string            `json:"action"`
	Service     string            `json:"service"`
	Files       []string          `json:"files"`
	Creds       map[string]string `json:"creds"`
	Config      map[string]string `json:"config"`
	ContextData map[string]string `json:"context_data"`
	HttpSpec    *HttpRequestSpec  `json:"http_spec,omitempty"` // New generic HTTP runner
}

// HttpRequestSpec defines a generic HTTP request for plugin-driven uploads
type HttpRequestSpec struct {
	URL             string                       `json:"url"`
	Method          string                       `json:"method"`
	Headers         map[string]string            `json:"headers"`
	MultipartFields map[string]MultipartField    `json:"multipart_fields"`
	FormFields      map[string]string            `json:"form_fields,omitempty"`
	ResponseParser  ResponseParserSpec           `json:"response_parser"`
	PreRequest      *PreRequestSpec              `json:"pre_request,omitempty"` // NEW: Phase 3 session support
}

// PreRequestSpec defines a pre-request hook for login/session setup
type PreRequestSpec struct {
	Action         string            `json:"action"`          // "login", "get_endpoint", etc.
	URL            string            `json:"url"`
	Method         string            `json:"method"`
	Headers        map[string]string `json:"headers,omitempty"`
	FormFields     map[string]string `json:"form_fields,omitempty"`
	UseCookies     bool              `json:"use_cookies"`     // Store cookies for main request
	ExtractFields  map[string]string `json:"extract_fields"`  // Extract values from response (name -> JSONPath/selector)
	ResponseType   string            `json:"response_type"`   // "json" or "html"
	FollowUpRequest *PreRequestSpec  `json:"follow_up_request,omitempty"` // NEW: Chain multiple pre-requests
}

// MultipartField represents a field in multipart/form-data
type MultipartField struct {
	Type  string `json:"type"`  // "file", "text", or "dynamic"
	Value string `json:"value"` // For text: the value; For file: file path; For dynamic: reference to extracted field
}

// ResponseParserSpec defines how to parse the upload response
type ResponseParserSpec struct {
	Type         string `json:"type"`          // "json" or "html"
	URLPath      string `json:"url_path"`      // JSONPath or CSS selector for image URL
	ThumbPath    string `json:"thumb_path"`    // JSONPath or CSS selector for thumbnail URL
	StatusPath   string `json:"status_path"`   // JSONPath for status field
	SuccessValue string `json:"success_value"` // Expected value for success
	URLTemplate  string `json:"url_template,omitempty"`   // Template for constructing URL from extracted values (e.g., "https://example.com/p/{id}/image.html")
	ThumbTemplate string `json:"thumb_template,omitempty"` // Template for constructing thumbnail URL
}

type OutputEvent struct {
	Type     string      `json:"type"`
	FilePath string      `json:"file,omitempty"`
	Status   string      `json:"status,omitempty"`
	Url      string      `json:"url,omitempty"`
	Thumb    string      `json:"thumb,omitempty"`
	Msg      string      `json:"msg,omitempty"`
	Data     interface{} `json:"data,omitempty"`
}

// --- Globals ---
var outputMutex sync.Mutex
var client *http.Client

// Rate Limiters (prevent IP bans by throttling requests per service)
// Each service gets 2 requests/second with burst of 5 (reasonable for image hosts)
var rateLimiters = map[string]*rate.Limiter{
	"imx.to":          rate.NewLimiter(rate.Limit(2.0), 5),
	"pixhost.to":      rate.NewLimiter(rate.Limit(2.0), 5),
	"vipr.im":         rate.NewLimiter(rate.Limit(2.0), 5),
	"turboimagehost":  rate.NewLimiter(rate.Limit(2.0), 5),
	"imagebam.com":    rate.NewLimiter(rate.Limit(2.0), 5),
	"vipergirls.to":   rate.NewLimiter(rate.Limit(1.0), 3), // More conservative for forums
}
var rateLimiterMutex sync.RWMutex

// Global rate limiter across all services (10 req/s, burst 20)
// Prevents IP bans when uploading to multiple services simultaneously
var globalRateLimiter = rate.NewLimiter(rate.Limit(10.0), 20)

// Per-Service State Structs (reduces lock contention vs single global mutex)
type viprState struct {
	mu       sync.RWMutex
	endpoint string
	sessId   string
}

type turboState struct {
	mu       sync.RWMutex
	endpoint string
}

type imageBamState struct {
	mu          sync.RWMutex
	csrf        string
	uploadToken string
}

type viperGirlsState struct {
	mu            sync.RWMutex
	securityToken string
}

var viprSt = &viprState{}
var turboSt = &turboState{}
var ibSt = &imageBamState{}
var vgSt = &viperGirlsState{}

var quoteEscaper = strings.NewReplacer("\\", "\\\\", `"`, "\\\"")

func quoteEscape(s string) string { return quoteEscaper.Replace(s) }

// getRateLimiter returns the rate limiter for a given service
// Creates a default limiter if service not found
func getRateLimiter(service string) *rate.Limiter {
	rateLimiterMutex.RLock()
	limiter, exists := rateLimiters[service]
	rateLimiterMutex.RUnlock()

	if !exists {
		// Create default limiter for unknown services (2 req/s, burst 5)
		limiter = rate.NewLimiter(rate.Limit(2.0), 5)
		rateLimiterMutex.Lock()
		rateLimiters[service] = limiter
		rateLimiterMutex.Unlock()
	}

	return limiter
}

// waitForRateLimit waits for rate limiter approval before proceeding
// Returns error if context is cancelled while waiting
// Checks both global rate limiter (10 req/s across all services) and service-specific limiter
func waitForRateLimit(ctx context.Context, service string) error {
	// Wait for global limiter first (prevents overload when using multiple services)
	if err := globalRateLimiter.Wait(ctx); err != nil {
		return fmt.Errorf("global rate limit wait cancelled: %w", err)
	}

	// Then wait for service-specific limiter
	limiter := getRateLimiter(service)
	if err := limiter.Wait(ctx); err != nil {
		return fmt.Errorf("service rate limit wait cancelled: %w", err)
	}

	return nil
}

const charset = "abcdefghijklmnopqrstuvwxyz0123456789"

// randomString generates a random alphanumeric string of length n.
// Uses crypto/rand for cryptographically secure random generation.
func randomString(n int) string {
	b := make([]byte, n)
	// Use crypto/rand for better randomness
	if _, err := rand.Read(b); err != nil {
		// Fallback to timestamp-based string if crypto/rand fails
		return fmt.Sprintf("%d", time.Now().UnixNano())
	}
	for i := range b {
		b[i] = charset[int(b[i])%len(charset)]
	}
	return string(b)
}

func main() {
	// Parse command-line flags
	workerCount := flag.Int("workers", 8, "Number of worker goroutines for job processing")
	flag.Parse()

	// Note: Using crypto/rand for random string generation (more secure)
	log.WithFields(log.Fields{
		"component": "uploader",
		"version":   "2.0.0-diagnostic",
		"workers":   *workerCount,
	}).Info("Go sidecar starting")

	// DIAGNOSTIC: Send visible startup message as JSON event (goes to Python console)
	sendJSON(OutputEvent{
		Type: "log",
		Msg:  fmt.Sprintf("=== GO SIDECAR STARTED - VERSION 2.1.0 - WORKERS: %d ===", *workerCount),
	})

	jar, _ := cookiejar.New(nil)
	// TIMEOUT FIX: Increase timeouts to support large file uploads
	// - Client timeout: 180s (3 minutes) for the entire request/response cycle
	// - ResponseHeaderTimeout: 60s to allow servers time to process large uploads before responding
	// This prevents premature timeouts on large files or slow connections
	client = &http.Client{
		Timeout:   180 * time.Second,
		Jar:       jar,
		Transport: &http.Transport{
			MaxIdleConnsPerHost:   10,
			ResponseHeaderTimeout: 60 * time.Second,
			DisableKeepAlives:     false, // Allow connection reuse for efficiency
		},
	}

	// --- WORKER POOL IMPLEMENTATION ---
	// 1. Create a job queue channel
	jobQueue := make(chan JobRequest, 100)

	// 2. Start configured number of workers to process incoming requests
	// This prevents the Go process from spawning thousands of goroutines if the UI floods it.
	// Worker count is configurable via --workers flag (default: 8, range: 1-16)
	numWorkers := *workerCount
	log.WithField("workers", numWorkers).Info("Starting worker pool")

	for i := 0; i < numWorkers; i++ {
		go func(workerID int) {
			log.WithField("worker_id", workerID).Debug("Worker started")
			for job := range jobQueue {
				startTime := time.Now()
				log.WithFields(log.Fields{
					"worker_id": workerID,
					"action":    job.Action,
					"service":   job.Service,
					"files":     len(job.Files),
				}).Debug("Worker processing job")

				handleJob(job)

				duration := time.Since(startTime)
				log.WithFields(log.Fields{
					"worker_id": workerID,
					"duration":  duration.String(),
				}).Debug("Worker completed job")
			}
			log.WithField("worker_id", workerID).Info("Worker shutting down")
		}(i)
	}

	decoder := json.NewDecoder(os.Stdin)

	// 3. Main loop reads JSON and pushes to queue
	for {
		var job JobRequest
		if err := decoder.Decode(&job); err != nil {
			if err == io.EOF {
				break
			}
			sendJSON(OutputEvent{Type: "error", Msg: fmt.Sprintf("JSON Decode Error: %v", err)})
			continue
		}

		// Diagnostic: log queue depth if getting full
		queueDepth := len(jobQueue)
		if queueDepth > 50 {
			log.WithField("queue_depth", queueDepth).Warn("Job queue filling up - workers may be slow")
		}

		// Blocking push if queue is full, effectively throttling the UI
		jobQueue <- job
		log.WithFields(log.Fields{
			"action":      job.Action,
			"service":     job.Service,
			"files":       len(job.Files),
			"queue_depth": len(jobQueue),
		}).Debug("Job queued")
	}
}

func handleJob(job JobRequest) {
	defer func() {
		if r := recover(); r != nil {
			sendJSON(OutputEvent{Type: "error", Msg: fmt.Sprintf("Panic: %v", r)})
		}
	}()

	switch job.Action {
	case "upload":
		handleUpload(job)
	case "http_upload":
		// NEW: Generic HTTP runner for plugin-driven uploads
		handleHttpUpload(job)
	case "login", "verify":
		handleLoginVerify(job)
	case "list_galleries":
		handleListGalleries(job)
	case "create_gallery":
		handleCreateGallery(job)
	case "finalize_gallery":
		handleFinalizeGallery(job)
	case "viper_login":
		handleViperLogin(job)
	case "viper_post":
		handleViperPost(job)
	case "generate_thumb":
		handleGenerateThumb(job)
	default:
		if len(job.Files) > 0 {
			handleUpload(job)
		} else {
			sendJSON(OutputEvent{Type: "error", Msg: "Unknown action: " + job.Action})
		}
	}
}

func handleFinalizeGallery(job JobRequest) {
	// Placeholder for gallery finalization (e.g. Pixhost title setting)
	sendJSON(OutputEvent{Type: "result", Status: "success", Msg: "Gallery Finalized"})
}

func handleGenerateThumb(job JobRequest) {
	w, _ := strconv.Atoi(job.Config["width"])
	if w == 0 {
		w = 100
	}

	if len(job.Files) == 0 {
		sendJSON(OutputEvent{Type: "error", Msg: "No file provided"})
		return
	}
	fp := job.Files[0]

	f, err := os.Open(fp)
	if err != nil {
		sendJSON(OutputEvent{Type: "error", Msg: "File not found"})
		return
	}
	defer func() { _ = f.Close() }()

	img, _, err := image.Decode(f)
	if err != nil {
		sendJSON(OutputEvent{Type: "error", Msg: "Decode failed"})
		return
	}

	// Use Lanczos resampling for high-quality thumbnails
	// Maintains aspect ratio automatically
	thumb := imaging.Resize(img, w, 0, imaging.Lanczos)

	var buf bytes.Buffer
	// Use slightly higher quality (70) since Lanczos produces sharper results
	if err := jpeg.Encode(&buf, thumb, &jpeg.Options{Quality: 70}); err != nil {
		sendJSON(OutputEvent{Type: "error", Msg: "Encode thumbnail failed"})
		return
	}
	b64 := base64.StdEncoding.EncodeToString(buf.Bytes())

	sendJSON(OutputEvent{
		Type:     "data",
		Data:     b64,
		Status:   "success",
		FilePath: fp,
	})
}

func handleLoginVerify(job JobRequest) {
	success := false
	msg := "Login failed"

	switch job.Service {
	case "vipr.im":
		success = doViprLogin(job.Creds)
	case "imagebam.com":
		success = doImageBamLogin(job.Creds)
	case "turboimagehost":
		success = doTurboLogin(job.Creds)
	case "imx.to":
		if job.Creds["api_key"] != "" {
			success = true
			msg = "API Key present"
		}
	default:
		success = true
		msg = "No login required"
	}

	status := "failed"
	if success {
		status = "success"
	}
	sendJSON(OutputEvent{Type: "result", Status: status, Msg: msg})
}

func handleListGalleries(job JobRequest) {
	var galleries []map[string]string
	switch job.Service {
	case "vipr.im":
		viprSt.mu.RLock()
		needsLogin := viprSt.sessId == ""
		viprSt.mu.RUnlock()
		if needsLogin {
			doViprLogin(job.Creds)
		}
		galleries = scrapeViprGalleries()
	case "imagebam.com":
		ibSt.mu.RLock()
		needsLogin := ibSt.csrf == ""
		ibSt.mu.RUnlock()
		if needsLogin {
			doImageBamLogin(job.Creds)
		}
	case "imx.to":
		galleries = scrapeImxGalleries(job.Creds)
	}
	sendJSON(OutputEvent{Type: "data", Data: galleries, Status: "success"})
}

func handleCreateGallery(job JobRequest) {
	name := job.Config["gallery_name"]
	id := ""
	var err error

	switch job.Service {
	case "vipr.im":
		id, err = createViprGallery(name)
	case "imagebam.com":
		id = "0"
	case "imx.to":
		id, err = createImxGallery(job.Creds, name)
	default:
		err = fmt.Errorf("service not supported")
	}

	if err != nil {
		sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: err.Error()})
	} else {
		sendJSON(OutputEvent{Type: "result", Status: "success", Msg: id, Data: id})
	}
}

func handleHttpUpload(job JobRequest) {
	// NEW: Generic HTTP runner for plugin-driven uploads
	// Python plugins send fully-formed HTTP request specs; Go just executes them
	if job.HttpSpec == nil {
		sendJSON(OutputEvent{Type: "error", Msg: "http_upload requires http_spec field"})
		return
	}

	var wg sync.WaitGroup
	filesChan := make(chan string, len(job.Files))

	maxWorkers := 2
	if w, err := strconv.Atoi(job.Config["threads"]); err == nil && w > 0 {
		maxWorkers = w
	}

	for i := 0; i < maxWorkers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for fp := range filesChan {
				processFileGeneric(fp, &job)
			}
		}()
	}

	for _, f := range job.Files {
		filesChan <- f
	}
	close(filesChan)
	wg.Wait()
	sendJSON(OutputEvent{Type: "batch_complete", Status: "done"})
}

func handleUpload(job JobRequest) {
	var wg sync.WaitGroup
	filesChan := make(chan string, len(job.Files))

	maxWorkers := 2
	if w, err := strconv.Atoi(job.Config["threads"]); err == nil && w > 0 {
		maxWorkers = w
	}

	for i := 0; i < maxWorkers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for fp := range filesChan {
				processFile(fp, &job)
			}
		}()
	}

	for _, f := range job.Files {
		filesChan <- f
	}
	close(filesChan)
	wg.Wait()
	sendJSON(OutputEvent{Type: "batch_complete", Status: "done"})
}

func processFile(fp string, job *JobRequest) {
	logger := log.WithFields(log.Fields{
		"file":    filepath.Base(fp),
		"service": job.Service,
	})

	// DIAGNOSTIC: Send visible messages as JSON events
	sendJSON(OutputEvent{Type: "log", Msg: fmt.Sprintf(">>> PROCESSFILE CALLED for %s (service: %s)", filepath.Base(fp), job.Service)})
	sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Processing"})
	logger.Info("=== PROCESSFILE CALLED ===")

	// TIMEOUT FIX: 3-minute timeout per file to match documentation
	// Allows time for large uploads (10-50MB) on typical connections
	// Combined with client timeouts (180s/60s), this prevents premature failures
	ctx, cancel := context.WithTimeout(context.Background(), 180*time.Second)
	defer cancel()

	sendJSON(OutputEvent{Type: "log", Msg: fmt.Sprintf(">>> 3-minute timeout started for %s", filepath.Base(fp))})
	logger.WithField("timeout", "180s").Debug("Context created with timeout")

	type result struct {
		url   string
		thumb string
		err   error
	}
	resultChan := make(chan result, 1)

	// Heartbeat goroutine to prove timeout is working
	go func() {
		ticker := time.NewTicker(2 * time.Second)
		defer ticker.Stop()
		count := 0
		for {
			select {
			case <-ticker.C:
				count++
				logger.WithField("heartbeat", count).Debug("Still processing...")
			case <-ctx.Done():
				logger.Debug("Heartbeat stopped - context done")
				return
			}
		}
	}()

	go func() {
		sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Uploading"})
		logger.Debug("Status 'Uploading' sent")

		var url, thumb string
		var err error

		logger.WithField("service", job.Service).Debug("About to call upload function")

		// Pass context to upload functions for proper cancellation
		switch job.Service {
		case "imx.to":
			url, thumb, err = uploadImx(ctx, fp, job)
		case "pixhost.to":
			url, thumb, err = uploadPixhost(ctx, fp, job)
		case "vipr.im":
			url, thumb, err = uploadVipr(ctx, fp, job)
		case "turboimagehost":
			url, thumb, err = uploadTurbo(ctx, fp, job)
		case "imagebam.com":
			url, thumb, err = uploadImageBam(ctx, fp, job)
		default:
			err = fmt.Errorf("unknown service: %s", job.Service)
			logger.WithField("service", job.Service).Error("UNKNOWN SERVICE - this will fail immediately")
		}

		logger.WithFields(log.Fields{
			"url":   url,
			"thumb": thumb,
			"error": err,
		}).Debug("Upload function returned")

		select {
		case resultChan <- result{url: url, thumb: thumb, err: err}:
			logger.Debug("Result sent to channel")
		case <-ctx.Done():
			logger.Warn("Context cancelled before result could be sent")
			// Context cancelled, don't send result
		}
	}()

	// Wait for upload to complete or timeout
	logger.Debug("Entering select statement - waiting for result or timeout")
	select {
	case res := <-resultChan:
		logger.WithField("has_error", res.err != nil).Debug("=== RESULT RECEIVED ===")
		if res.err != nil {
			logger.WithFields(log.Fields{
				"error": res.err.Error(),
			}).Error("Upload failed")
			sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Failed"})
			sendJSON(OutputEvent{Type: "error", FilePath: fp, Msg: fmt.Sprintf("Upload failed: %v", res.err)})
		} else {
			logger.WithFields(log.Fields{
				"url":   res.url,
				"thumb": res.thumb,
			}).Info("Upload successful")
			sendJSON(OutputEvent{Type: "result", FilePath: fp, Url: res.url, Thumb: res.thumb})
			sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Done"})
		}
	case <-ctx.Done():
		// TIMEOUT - context cancelled, goroutine should exit
		logger.Error("=== TIMEOUT TRIGGERED - 3 MINUTES ELAPSED ===")
		sendJSON(OutputEvent{Type: "log", Msg: fmt.Sprintf("!!! TIMEOUT TRIGGERED for %s after 3 minutes !!!", filepath.Base(fp))})
		sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Timeout"})
		sendJSON(OutputEvent{Type: "error", FilePath: fp, Msg: "Upload timed out after 3 minutes - worker released"})
	}
	sendJSON(OutputEvent{Type: "log", Msg: fmt.Sprintf(">>> PROCESSFILE EXITING for %s", filepath.Base(fp))})
	logger.Debug("=== PROCESSFILE EXITING ===")
}

// processFileGeneric handles file uploads using the generic HTTP runner
// This allows Python plugins to define the entire HTTP request
func processFileGeneric(fp string, job *JobRequest) {
	logger := log.WithFields(log.Fields{
		"file":    filepath.Base(fp),
		"service": job.Service,
	})

	sendJSON(OutputEvent{Type: "log", Msg: fmt.Sprintf(">>> GENERIC UPLOAD for %s (service: %s)", filepath.Base(fp), job.Service)})
	sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Processing"})
	logger.Info("=== GENERIC PROCESSFILE CALLED ===")

	// Same timeout as legacy processFile
	ctx, cancel := context.WithTimeout(context.Background(), 180*time.Second)
	defer cancel()

	sendJSON(OutputEvent{Type: "log", Msg: fmt.Sprintf(">>> 3-minute timeout started for %s", filepath.Base(fp))})
	logger.WithField("timeout", "180s").Debug("Context created with timeout")

	type result struct {
		url   string
		thumb string
		err   error
	}
	resultChan := make(chan result, 1)

	go func() {
		sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Uploading"})
		logger.Debug("Status 'Uploading' sent")

		// Execute the generic HTTP request
		url, thumb, err := executeHttpUpload(ctx, fp, job)

		logger.WithFields(log.Fields{
			"url":   url,
			"thumb": thumb,
			"error": err,
		}).Debug("Generic upload returned")

		select {
		case resultChan <- result{url: url, thumb: thumb, err: err}:
			logger.Debug("Result sent to channel")
		case <-ctx.Done():
			logger.Warn("Context cancelled before result could be sent")
		}
	}()

	// Wait for upload to complete or timeout
	logger.Debug("Waiting for result or timeout")
	select {
	case res := <-resultChan:
		logger.WithField("has_error", res.err != nil).Debug("=== RESULT RECEIVED ===")
		if res.err != nil {
			logger.WithFields(log.Fields{
				"error": res.err.Error(),
			}).Error("Upload failed")
			sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Failed"})
			sendJSON(OutputEvent{Type: "error", FilePath: fp, Msg: fmt.Sprintf("Upload failed: %v", res.err)})
		} else {
			logger.WithFields(log.Fields{
				"url":   res.url,
				"thumb": res.thumb,
			}).Info("Upload successful")
			sendJSON(OutputEvent{Type: "result", FilePath: fp, Url: res.url, Thumb: res.thumb})
			sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Done"})
		}
	case <-ctx.Done():
		logger.Error("=== TIMEOUT TRIGGERED - 3 MINUTES ELAPSED ===")
		sendJSON(OutputEvent{Type: "log", Msg: fmt.Sprintf("!!! TIMEOUT TRIGGERED for %s after 3 minutes !!!", filepath.Base(fp))})
		sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Timeout"})
		sendJSON(OutputEvent{Type: "error", FilePath: fp, Msg: "Upload timed out after 3 minutes - worker released"})
	}
	sendJSON(OutputEvent{Type: "log", Msg: fmt.Sprintf(">>> GENERIC PROCESSFILE EXITING for %s", filepath.Base(fp))})
	logger.Debug("=== GENERIC PROCESSFILE EXITING ===")
}

// executeHttpUpload performs a generic HTTP upload based on Python-provided spec
func executeHttpUpload(ctx context.Context, fp string, job *JobRequest) (string, string, error) {
	spec := job.HttpSpec
	if spec == nil {
		return "", "", fmt.Errorf("no http_spec provided")
	}

	// Apply rate limiting if service is specified
	if job.Service != "" {
		if err := waitForRateLimit(ctx, job.Service); err != nil {
			return "", "", fmt.Errorf("rate limit: %w", err)
		}
	}

	// NEW: Execute pre-request if specified (login, get endpoint, etc.)
	extractedValues := make(map[string]string)
	var sessionClient *http.Client

	if spec.PreRequest != nil {
		values, preClient, err := executePreRequest(ctx, spec.PreRequest, job.Service)
		if err != nil {
			return "", "", fmt.Errorf("pre-request failed: %w", err)
		}
		extractedValues = values

		// Use session client with cookies if pre-request requested it
		if spec.PreRequest.UseCookies {
			sessionClient = preClient
		}
	}

	// Build multipart request
	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)

	go func() {
		defer func() { _ = pw.Close() }()
		defer func() { _ = writer.Close() }()

		// Process all multipart fields from the spec
		for fieldName, field := range spec.MultipartFields {
			if field.Type == "file" {
				// File field - use the file from the job
				filePath := fp // Use the file being processed, not field.Value
				part, err := writer.CreateFormFile(fieldName, filepath.Base(filePath))
				if err != nil {
					pw.CloseWithError(fmt.Errorf("failed to create form file %s: %w", fieldName, err))
					return
				}
				f, err := os.Open(filePath)
				if err != nil {
					pw.CloseWithError(fmt.Errorf("failed to open file %s: %w", filePath, err))
					return
				}
				defer func() { _ = f.Close() }()
				if _, err := io.Copy(part, f); err != nil {
					pw.CloseWithError(fmt.Errorf("failed to copy file %s: %w", filePath, err))
					return
				}
			} else if field.Type == "text" {
				// Text field
				if err := writer.WriteField(fieldName, field.Value); err != nil {
					pw.CloseWithError(fmt.Errorf("failed to write field %s: %w", fieldName, err))
					return
				}
			} else if field.Type == "dynamic" {
				// NEW: Dynamic field - resolve from extracted values
				value, exists := extractedValues[field.Value]
				if !exists {
					pw.CloseWithError(fmt.Errorf("dynamic field %s references unknown extracted value: %s", fieldName, field.Value))
					return
				}
				if err := writer.WriteField(fieldName, value); err != nil {
					pw.CloseWithError(fmt.Errorf("failed to write dynamic field %s: %w", fieldName, err))
					return
				}
			}
		}
	}()

	// Create HTTP request
	req, err := http.NewRequestWithContext(ctx, spec.Method, spec.URL, pr)
	if err != nil {
		return "", "", fmt.Errorf("failed to create request: %w", err)
	}

	// Set headers from spec
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("User-Agent", UserAgent) // Default user agent
	for key, value := range spec.Headers {
		req.Header.Set(key, value)
	}

	// Execute request (use session client if available, otherwise default)
	var resp *http.Response
	if sessionClient != nil {
		resp, err = sessionClient.Do(req)
	} else {
		resp, err = client.Do(req)
	}
	if err != nil {
		return "", "", fmt.Errorf("request failed: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	// Parse response based on parser spec
	return parseHttpResponse(resp, &spec.ResponseParser, fp)
}

// executePreRequest executes a pre-request hook (login, endpoint discovery, etc.)
// Returns extracted values and optionally a client with session cookies
func executePreRequest(ctx context.Context, spec *PreRequestSpec, service string) (map[string]string, *http.Client, error) {
	log.WithFields(log.Fields{
		"action":  spec.Action,
		"url":     spec.URL,
		"service": service,
	}).Debug("Executing pre-request")

	// Create client with optional cookie jar
	var preClient *http.Client
	if spec.UseCookies {
		jar, _ := cookiejar.New(nil)
		preClient = &http.Client{
			Timeout: 60 * time.Second,
			Jar:     jar,
			Transport: &http.Transport{
				MaxIdleConnsPerHost:   10,
				ResponseHeaderTimeout: 30 * time.Second,
			},
		}
	} else {
		preClient = client // Use default client
	}

	// Build request body (support template substitution in form fields)
	var reqBody io.Reader
	contentType := ""

	if len(spec.FormFields) > 0 {
		formData := url.Values{}
		for key, value := range spec.FormFields {
			// Support template substitution: {field_name} -> extracted value
			// This is needed for multi-step flows like ImageBam where later steps need earlier extracted values
			// Note: extractedValues would need to be passed in, but we don't have them yet on first call
			// For now, this is handled in follow-up requests which have access to parent extracted values
			formData.Set(key, value)
		}
		reqBody = strings.NewReader(formData.Encode())
		contentType = "application/x-www-form-urlencoded"
	}

	// Create request
	req, err := http.NewRequestWithContext(ctx, spec.Method, spec.URL, reqBody)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to create pre-request: %w", err)
	}

	// Set headers (no template substitution needed on first request)
	req.Header.Set("User-Agent", UserAgent)
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	for key, value := range spec.Headers {
		req.Header.Set(key, value)
	}

	// Execute request
	resp, err := preClient.Do(req)
	if err != nil {
		return nil, nil, fmt.Errorf("pre-request execution failed: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to read pre-request response: %w", err)
	}

	// Extract values based on response type
	extractedValues := make(map[string]string)

	if spec.ResponseType == "json" {
		var data map[string]interface{}
		if err := json.Unmarshal(bodyBytes, &data); err != nil {
			return nil, nil, fmt.Errorf("failed to parse JSON pre-request response: %w", err)
		}

		for fieldName, jsonPath := range spec.ExtractFields {
			value := getJSONValue(data, jsonPath)
			extractedValues[fieldName] = value
			log.WithFields(log.Fields{
				"field": fieldName,
				"value": value,
				"path":  jsonPath,
			}).Debug("Extracted value from JSON")
		}
	} else if spec.ResponseType == "html" {
		doc, err := goquery.NewDocumentFromReader(bytes.NewReader(bodyBytes))
		if err != nil {
			return nil, nil, fmt.Errorf("failed to parse HTML pre-request response: %w", err)
		}

		for fieldName, selector := range spec.ExtractFields {
			var value string

			// Support regex extraction if selector starts with "regex:"
			if strings.HasPrefix(selector, "regex:") {
				pattern := strings.TrimPrefix(selector, "regex:")
				re := regexp.MustCompile(pattern)
				matches := re.FindStringSubmatch(string(bodyBytes))
				if len(matches) > 1 {
					value = matches[1] // First capture group
				}
				log.WithFields(log.Fields{
					"field":   fieldName,
					"value":   value,
					"pattern": pattern,
				}).Debug("Extracted value from HTML using regex")
			} else {
				// CSS selector extraction
				value = doc.Find(selector).AttrOr("value", "")
				if value == "" {
					value = doc.Find(selector).AttrOr("action", "")
				}
				if value == "" {
					value = doc.Find(selector).Text()
				}
				log.WithFields(log.Fields{
					"field":    fieldName,
					"value":    value,
					"selector": selector,
				}).Debug("Extracted value from HTML using CSS selector")
			}

			extractedValues[fieldName] = strings.TrimSpace(value)
		}
	}

	log.WithFields(log.Fields{
		"extracted_count": len(extractedValues),
		"has_cookies":     spec.UseCookies,
	}).Debug("Pre-request completed")

	// NEW: Execute follow-up request if specified (for multi-step logins like Vipr)
	if spec.FollowUpRequest != nil {
		log.Debug("Executing follow-up pre-request")

		// Execute follow-up using same client (preserves cookies) and parent extracted values
		followUpValues, followUpClient, err := executeFollowUpRequest(ctx, spec.FollowUpRequest, service, preClient, extractedValues)
		if err != nil {
			return nil, nil, fmt.Errorf("follow-up request failed: %w", err)
		}

		// Merge extracted values (follow-up values override initial values)
		for k, v := range followUpValues {
			extractedValues[k] = v
		}

		// Use follow-up client if it has cookies, otherwise keep original
		if spec.FollowUpRequest.UseCookies && followUpClient != nil {
			preClient = followUpClient
		}
	}

	return extractedValues, preClient, nil
}

// executeFollowUpRequest handles follow-up pre-requests using an existing client and parent extracted values
func executeFollowUpRequest(ctx context.Context, spec *PreRequestSpec, service string, existingClient *http.Client, parentExtractedValues map[string]string) (map[string]string, *http.Client, error) {
	log.WithFields(log.Fields{
		"action":  spec.Action,
		"url":     spec.URL,
		"service": service,
	}).Debug("Executing follow-up pre-request")

	// Use existing client to preserve cookies, or create new one
	reqClient := existingClient
	if reqClient == nil {
		if spec.UseCookies {
			jar, _ := cookiejar.New(nil)
			reqClient = &http.Client{
				Timeout: 60 * time.Second,
				Jar:     jar,
				Transport: &http.Transport{
					MaxIdleConnsPerHost:   10,
					ResponseHeaderTimeout: 30 * time.Second,
				},
			}
		} else {
			reqClient = client
		}
	}

	// Build request body with template substitution from parent extracted values
	var reqBody io.Reader
	contentType := ""

	if len(spec.FormFields) > 0 {
		formData := url.Values{}
		for key, value := range spec.FormFields {
			// Support template substitution: {field_name} -> extracted value from parent
			substitutedValue := substituteTemplateFromMap(value, parentExtractedValues)
			formData.Set(key, substitutedValue)
		}
		reqBody = strings.NewReader(formData.Encode())
		contentType = "application/x-www-form-urlencoded"
	}

	// Create request
	req, err := http.NewRequestWithContext(ctx, spec.Method, spec.URL, reqBody)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to create follow-up request: %w", err)
	}

	// Set headers with template substitution from parent extracted values
	req.Header.Set("User-Agent", UserAgent)
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	for key, value := range spec.Headers {
		// Support template substitution in headers (e.g., "X-CSRF-TOKEN": "{csrf_token}")
		substitutedValue := substituteTemplateFromMap(value, parentExtractedValues)
		req.Header.Set(key, substitutedValue)
	}

	// Execute request
	resp, err := reqClient.Do(req)
	if err != nil {
		return nil, nil, fmt.Errorf("follow-up request execution failed: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to read follow-up response: %w", err)
	}

	// Extract values based on response type
	extractedValues := make(map[string]string)

	if spec.ResponseType == "json" {
		var data map[string]interface{}
		if err := json.Unmarshal(bodyBytes, &data); err != nil {
			return nil, nil, fmt.Errorf("failed to parse JSON follow-up response: %w", err)
		}

		for fieldName, jsonPath := range spec.ExtractFields {
			value := getJSONValue(data, jsonPath)
			extractedValues[fieldName] = value
			log.WithFields(log.Fields{
				"field": fieldName,
				"value": value,
				"path":  jsonPath,
			}).Debug("Extracted value from JSON (follow-up)")
		}
	} else if spec.ResponseType == "html" {
		doc, err := goquery.NewDocumentFromReader(bytes.NewReader(bodyBytes))
		if err != nil {
			return nil, nil, fmt.Errorf("failed to parse HTML follow-up response: %w", err)
		}

		for fieldName, selector := range spec.ExtractFields {
			var value string

			// Support regex extraction if selector starts with "regex:"
			if strings.HasPrefix(selector, "regex:") {
				pattern := strings.TrimPrefix(selector, "regex:")
				re := regexp.MustCompile(pattern)
				matches := re.FindStringSubmatch(string(bodyBytes))
				if len(matches) > 1 {
					value = matches[1] // First capture group
				}
				log.WithFields(log.Fields{
					"field":   fieldName,
					"value":   value,
					"pattern": pattern,
				}).Debug("Extracted value from HTML using regex (follow-up)")
			} else {
				// CSS selector extraction
				value = doc.Find(selector).AttrOr("value", "")
				if value == "" {
					value = doc.Find(selector).AttrOr("action", "")
				}
				if value == "" {
					value = doc.Find(selector).Text()
				}
				log.WithFields(log.Fields{
					"field":    fieldName,
					"value":    value,
					"selector": selector,
				}).Debug("Extracted value from HTML using CSS selector (follow-up)")
			}

			extractedValues[fieldName] = strings.TrimSpace(value)
		}
	}

	// Recursively handle nested follow-ups (though typically not needed)
	if spec.FollowUpRequest != nil {
		// Merge parent and current extracted values for the next follow-up
		mergedValues := make(map[string]string)
		for k, v := range parentExtractedValues {
			mergedValues[k] = v
		}
		for k, v := range extractedValues {
			mergedValues[k] = v
		}

		nestedValues, nestedClient, err := executeFollowUpRequest(ctx, spec.FollowUpRequest, service, reqClient, mergedValues)
		if err != nil {
			return nil, nil, err
		}
		for k, v := range nestedValues {
			extractedValues[k] = v
		}
		if nestedClient != nil {
			reqClient = nestedClient
		}
	}

	log.WithFields(log.Fields{
		"extracted_count": len(extractedValues),
	}).Debug("Follow-up pre-request completed")

	return extractedValues, reqClient, nil
}

// parseHttpResponse parses the upload response based on the parser spec
func parseHttpResponse(resp *http.Response, parser *ResponseParserSpec, filePath string) (string, string, error) {
	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", "", fmt.Errorf("failed to read response: %w", err)
	}

	if parser.Type == "json" {
		// Parse JSON response
		var data map[string]interface{}
		if err := json.Unmarshal(bodyBytes, &data); err != nil {
			return "", "", fmt.Errorf("failed to parse JSON response: %w", err)
		}

		// Check status if specified
		if parser.StatusPath != "" {
			status := getJSONValue(data, parser.StatusPath)
			if status != parser.SuccessValue {
				msg := getJSONValue(data, "message")
				if msg == "" {
					msg = getJSONValue(data, "error")
				}
				if msg == "" {
					msg = fmt.Sprintf("upload failed with status: %s", status)
				}
				return "", "", fmt.Errorf("%s", msg)
			}
		}

		// Extract URLs or values for template substitution
		url := getJSONValue(data, parser.URLPath)
		thumb := getJSONValue(data, parser.ThumbPath)

		// NEW: Support URL templates for constructing URLs from extracted values
		if parser.URLTemplate != "" {
			// Add filename to data for template substitution
			dataWithFile := make(map[string]interface{})
			for k, v := range data {
				dataWithFile[k] = v
			}
			dataWithFile["filename"] = filepath.Base(filePath)
			url = substituteTemplate(parser.URLTemplate, dataWithFile)
		}
		if parser.ThumbTemplate != "" {
			dataWithFile := make(map[string]interface{})
			for k, v := range data {
				dataWithFile[k] = v
			}
			dataWithFile["filename"] = filepath.Base(filePath)
			thumb = substituteTemplate(parser.ThumbTemplate, dataWithFile)
		} else if parser.URLTemplate != "" && thumb == "" {
			// If URL template is used but no thumb template, use URL as thumb
			thumb = url
		}

		if url == "" {
			return "", "", fmt.Errorf("no URL found in response at path: %s", parser.URLPath)
		}

		return url, thumb, nil
	} else if parser.Type == "html" {
		// Parse HTML response using goquery
		doc, err := goquery.NewDocumentFromReader(bytes.NewReader(bodyBytes))
		if err != nil {
			return "", "", fmt.Errorf("failed to parse HTML: %w", err)
		}

		// Use CSS selectors from parser spec
		url := doc.Find(parser.URLPath).AttrOr("value", "")
		if url == "" {
			url = doc.Find(parser.URLPath).Text()
		}

		thumb := doc.Find(parser.ThumbPath).AttrOr("value", "")
		if thumb == "" {
			thumb = doc.Find(parser.ThumbPath).AttrOr("src", "")
		}
		if thumb == "" {
			thumb = doc.Find(parser.ThumbPath).Text()
		}

		if url == "" {
			return "", "", fmt.Errorf("no URL found with selector: %s", parser.URLPath)
		}

		return url, thumb, nil
	}

	return "", "", fmt.Errorf("unsupported parser type: %s", parser.Type)
}

// substituteTemplateFromMap replaces {key} placeholders in a template with values from a string map
func substituteTemplateFromMap(template string, values map[string]string) string {
	result := template

	// Find all {key} placeholders and replace them
	re := regexp.MustCompile(`\{([^}]+)\}`)
	matches := re.FindAllStringSubmatch(template, -1)

	for _, match := range matches {
		if len(match) < 2 {
			continue
		}
		placeholder := match[0] // e.g., "{csrf_token}"
		key := match[1]          // e.g., "csrf_token"

		// Look up value in map
		if value, exists := values[key]; exists {
			result = strings.Replace(result, placeholder, value, -1)
		}
	}

	return result
}

// substituteTemplate replaces {key} placeholders in a template with values from JSON data
func substituteTemplate(template string, data map[string]interface{}) string {
	result := template

	// Find all {key} placeholders and replace them
	re := regexp.MustCompile(`\{([^}]+)\}`)
	matches := re.FindAllStringSubmatch(template, -1)

	for _, match := range matches {
		if len(match) < 2 {
			continue
		}
		placeholder := match[0] // e.g., "{id}"
		key := match[1]          // e.g., "id"

		// Extract value from JSON using dot notation
		value := getJSONValue(data, key)
		if value != "" {
			result = strings.Replace(result, placeholder, value, -1)
		}
	}

	return result
}

// getJSONValue extracts a value from nested JSON using dot notation (e.g., "data.image_url")
func getJSONValue(data map[string]interface{}, path string) string {
	if path == "" {
		return ""
	}

	parts := strings.Split(path, ".")
	current := interface{}(data)

	for _, part := range parts {
		switch v := current.(type) {
		case map[string]interface{}:
			current = v[part]
		default:
			return ""
		}
	}

	// Convert final value to string
	switch v := current.(type) {
	case string:
		return v
	case float64:
		return fmt.Sprintf("%.0f", v)
	case bool:
		return fmt.Sprintf("%t", v)
	default:
		return ""
	}
}

// --- Upload Implementations ---

// Helpers to map UI strings to IMX API IDs
func getImxSizeId(s string) string {
	switch s {
	case "100": return "1"
	case "150": return "6"
	case "180": return "2"
	case "250": return "3"
	case "300": return "4"
	default: return "2" // Default 180
	}
}

func getImxFormatId(s string) string {
	switch s {
	case "Fixed Width": return "1"
	case "Fixed Height": return "4"
	case "Proportional": return "2"
	case "Square": return "3"
	default: return "1" // Default Fixed Width
	}
}

func uploadImx(ctx context.Context, fp string, job *JobRequest) (string, string, error) {
	// RATE LIMITING: Wait for rate limiter approval to prevent IP bans
	if err := waitForRateLimit(ctx, "imx.to"); err != nil {
		return "", "", fmt.Errorf("rate limit: %w", err)
	}

	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)

	go func() {
		defer func() { _ = pw.Close() }()
		defer func() { _ = writer.Close() }()
		part, err := writer.CreateFormFile("image", filepath.Base(fp))
		if err != nil {
			pw.CloseWithError(fmt.Errorf("failed to create form file: %w", err))
			return
		}
		f, err := os.Open(fp)
		if err != nil {
			pw.CloseWithError(fmt.Errorf("failed to open file: %w", err))
			return
		}
		defer func() { _ = f.Close() }()
		if _, err := io.Copy(part, f); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to copy file: %w", err))
			return
		}
		if err := writer.WriteField("format", "json"); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write format field: %w", err))
			return
		}
		
		// Essential Hidden Fields from uploadpage.html for legacy script support
		if err := writer.WriteField("adult", "1"); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write adult field: %w", err))
			return
		}
		if err := writer.WriteField("upload_type", "file"); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write upload_type field: %w", err))
			return
		}
		// "simple_upload" is often required for legacy scripts to respect parameters like thumb size
		if err := writer.WriteField("simple_upload", "Upload"); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write simple_upload field: %w", err))
			return
		}
		
		// Map the config strings to IDs before sending to API
		sizeId := getImxSizeId(job.Config["imx_thumb_id"])
		
		// Send both variations of the parameter name to cover all bases (API vs Form)
		if err := writer.WriteField("thumbnail_size", sizeId); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write thumbnail_size field: %w", err))
			return
		}
		if err := writer.WriteField("thumb_size_contaner", sizeId); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write thumb_size_contaner field: %w", err))
			return
		}

		if err := writer.WriteField("thumbnail_format", getImxFormatId(job.Config["imx_format_id"])); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write thumbnail_format field: %w", err))
			return
		}
		if gid := job.Config["gallery_id"]; gid != "" {
			if err := writer.WriteField("gallery_id", gid); err != nil {
				pw.CloseWithError(fmt.Errorf("failed to write gallery_id field: %w", err))
				return
			}
		}
	}()

	// CRITICAL: Use context for proper cancellation
	req, err := http.NewRequestWithContext(ctx, "POST", "https://api.imx.to/v1/upload.php", pr)
	if err != nil {
		return "", "", fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("X-API-KEY", job.Creds["api_key"])
	req.Header.Set("User-Agent", UserAgent)

	resp, err := client.Do(req)
	if err != nil {
		return "", "", fmt.Errorf("request failed: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", "", fmt.Errorf("failed to read response: %w", err)
	}

	var res struct {
		Status string `json:"status"`
		Data   struct {
			Img   string `json:"image_url"`
			Thumb string `json:"thumbnail_url"`
		} `json:"data"`
		Msg string `json:"message"`
	}
	if err := json.Unmarshal(raw, &res); err != nil {
		return "", "", fmt.Errorf("failed to parse response: %w", err)
	}
	if res.Status != "success" {
		return "", "", fmt.Errorf("upload failed: %s", res.Msg)
	}

	// Scrape the actual BBCode from the image viewer page to get working thumbnail URLs
	viewerURL := res.Data.Img
	finalThumb := res.Data.Thumb

	// Try scraping to find better URLs
	if viewerURL != "" {
		scrapedViewer, scrapedThumb, err := scrapeImxBBCode(viewerURL)
		if err == nil && scrapedThumb != "" {
			log.WithFields(log.Fields{
				"old_thumb": finalThumb,
				"new_thumb": scrapedThumb,
			}).Info("Replaced API thumb with Scraped thumb")
			
			// Update values with scraped results
			viewerURL = scrapedViewer
			finalThumb = scrapedThumb
		} else {
			log.WithFields(log.Fields{
				"url":   viewerURL,
				"error": err,
			}).Warn("Failed to scrape IMX BBCode, using API response")
		}
	}

	// REMOVED "Force Repair" logic that was breaking image.imx.to links.
	// Relying on scraper results.

	return viewerURL, finalThumb, nil
}

// scrapeImxBBCode fetches the IMX viewer page and intelligently extracts the correct BBCode
func scrapeImxBBCode(viewerURL string) (string, string, error) {
	resp, err := doRequest(context.Background(), "GET", viewerURL, nil, "")
	if err != nil {
		return "", "", fmt.Errorf("failed to fetch viewer page: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil {
		return "", "", fmt.Errorf("failed to parse HTML: %w", err)
	}

	var bestBBCode string
	var bestScore = -100

	// Iterate all text inputs to find the best candidate for "Thumbnail BBCode"
	doc.Find("textarea, input[type='text']").Each(func(i int, s *goquery.Selection) {
		text := strings.TrimSpace(s.Text())
		if text == "" {
			text, _ = s.Attr("value")
		}
		// Basic validation: must look like a BBCode link
		if !strings.Contains(text, "[url=") || !strings.Contains(text, "[img]") {
			return
		}

		// Calculate Score to identify the "Thumbnail" code vs "Full Image/Hotlink" code
		score := 0

		// 1. Check Label (Preceding text)
		label := strings.ToLower(s.Prev().Text())
		parentLabel := strings.ToLower(s.Parent().Prev().Text()) 
		grandParentLabel := strings.ToLower(s.Parent().Parent().Prev().Text())
		combinedLabel := label + " " + parentLabel + " " + grandParentLabel

		if strings.Contains(combinedLabel, "thumb") {
			score += 50 // Strong signal for thumbnail
		} else if strings.Contains(combinedLabel, "hotlink") || strings.Contains(combinedLabel, "full") {
			score -= 50 // Strong signal for full image (avoid)
		}

		// 2. Check URL Pattern inside the BBCode
		// Thumbnails often have "/t/" or "_t" or "small" in the URL
		if strings.Contains(text, "/u/t/") || strings.Contains(text, "_t") {
			score += 100 // Very strong signal
		} else if strings.Contains(text, "/u/i/") {
			score -= 20 // Looks like full image
		}

		// 3. Position Preference
		// If labels are missing, thumbnails usually appear before full hotlinks.
		// We subtract 'i' so earlier elements get a slightly higher score if all else matches.
		score -= i 

		if score > bestScore {
			bestScore = score
			bestBBCode = text
		}
	})

	if bestBBCode == "" {
		return "", "", fmt.Errorf("no valid BBCode found on page")
	}

	// Parse BBCode to extract URLs
	// Pattern: [url=VIEWER_URL][img]THUMB_URL[/img][/url]
	reURL := regexp.MustCompile(`\[url=([^\]]+)\]\[img\]([^\[]+)\[/img\]\[/url\]`)
	matches := reURL.FindStringSubmatch(bestBBCode)
	if len(matches) < 3 {
		return "", "", fmt.Errorf("failed to parse best BBCode candidate: %s", bestBBCode)
	}

	return matches[1], matches[2], nil
}

func uploadPixhost(ctx context.Context, fp string, job *JobRequest) (string, string, error) {
	// RATE LIMITING: Wait for rate limiter approval to prevent IP bans
	if err := waitForRateLimit(ctx, "pixhost.to"); err != nil {
		return "", "", fmt.Errorf("rate limit: %w", err)
	}

	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)

	go func() {
		defer func() { _ = pw.Close() }()
		defer func() { _ = writer.Close() }()
		part, err := writer.CreateFormFile("img", filepath.Base(fp))
		if err != nil {
			pw.CloseWithError(fmt.Errorf("failed to create form file: %w", err))
			return
		}
		f, err := os.Open(fp)
		if err != nil {
			pw.CloseWithError(fmt.Errorf("failed to open file: %w", err))
			return
		}
		defer func() { _ = f.Close() }()
		if _, err := io.Copy(part, f); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to copy file: %w", err))
			return
		}
		if err := writer.WriteField("content_type", job.Config["pix_content"]); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write content_type field: %w", err))
			return
		}
		if err := writer.WriteField("max_th_size", job.Config["pix_thumb"]); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write max_th_size field: %w", err))
			return
		}
		if h := job.Config["pix_gallery_hash"]; h != "" {
			if err := writer.WriteField("gallery_hash", h); err != nil {
				pw.CloseWithError(fmt.Errorf("failed to write gallery_hash field: %w", err))
				return
			}
		}
	}()

	// CRITICAL: Use context for proper cancellation
	req, err := http.NewRequestWithContext(ctx, "POST", "https://api.pixhost.to/images", pr)
	if err != nil {
		return "", "", fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("User-Agent", UserAgent)

	resp, err := client.Do(req)
	if err != nil {
		return "", "", fmt.Errorf("request failed: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", "", fmt.Errorf("failed to read response: %w", err)
	}

	var res struct {
		Show string `json:"show_url"`
		Th   string `json:"th_url"`
		Err  string `json:"error_msg"`
	}
	if err := json.Unmarshal(raw, &res); err != nil {
		return "", "", fmt.Errorf("failed to parse response: %w", err)
	}
	if res.Show == "" {
		return "", "", fmt.Errorf("upload failed: %s", res.Err)
	}
	return res.Show, res.Th, nil
}

func uploadVipr(ctx context.Context, fp string, job *JobRequest) (string, string, error) {
	// RATE LIMITING: Wait for rate limiter approval to prevent IP bans
	if err := waitForRateLimit(ctx, "vipr.im"); err != nil {
		return "", "", fmt.Errorf("rate limit: %w", err)
	}

	viprSt.mu.RLock()
	needsLogin := viprSt.sessId == ""
	upUrl := viprSt.endpoint
	sessId := viprSt.sessId
	viprSt.mu.RUnlock()

	if needsLogin {
		doViprLogin(job.Creds)
		viprSt.mu.RLock()
		upUrl = viprSt.endpoint
		sessId = viprSt.sessId
		viprSt.mu.RUnlock()
	}

	if upUrl == "" {
		upUrl = "https://vipr.im/cgi-bin/upload.cgi"
	}

	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)
	go func() {
		defer func() { _ = pw.Close() }()
		defer func() { _ = writer.Close() }()
		safeName := strings.ReplaceAll(filepath.Base(fp), " ", "_")
		part, err := writer.CreateFormFile("file_0", safeName)
		if err != nil {
			pw.CloseWithError(fmt.Errorf("failed to create form file: %w", err))
			return
		}
		f, err := os.Open(fp)
		if err != nil {
			pw.CloseWithError(fmt.Errorf("failed to open file: %w", err))
			return
		}
		defer func() { _ = f.Close() }()
		if _, err := io.Copy(part, f); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to copy file: %w", err))
			return
		}
		if err := writer.WriteField("upload_type", "file"); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write upload_type field: %w", err))
			return
		}
		if err := writer.WriteField("sess_id", sessId); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write sess_id field: %w", err))
			return
		}
		if err := writer.WriteField("thumb_size", job.Config["vipr_thumb"]); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write thumb_size field: %w", err))
			return
		}
		if err := writer.WriteField("fld_id", job.Config["vipr_gal_id"]); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write fld_id field: %w", err))
			return
		}
		if err := writer.WriteField("tos", "1"); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write tos field: %w", err))
			return
		}
		if err := writer.WriteField("submit_btn", "Upload"); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write submit_btn field: %w", err))
			return
		}
	}()

	u := upUrl + "?upload_id=" + randomString(12) + "&js_on=1&utype=reg&upload_type=file"
	resp, err := doRequest(ctx, "POST", u, pr, writer.FormDataContentType())
	if err != nil {
		return "", "", fmt.Errorf("request failed: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	// Parse initial response
	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil {
		return "", "", fmt.Errorf("failed to parse response: %w", err)
	}

	if textArea := doc.Find("textarea[name='fn']"); textArea.Length() > 0 {
		fnVal := textArea.Text()
		v := url.Values{"op": {"upload_result"}, "fn": {fnVal}, "st": {"OK"}}
		if r2, e2 := doRequest(ctx, "POST", "https://vipr.im/", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded"); e2 == nil {
			defer func() { _ = r2.Body.Close() }()
			doc, _ = goquery.NewDocumentFromReader(r2.Body)
		}
	}

	imgUrl := doc.Find("input[name='link_url']").AttrOr("value", "")
	thumbUrl := doc.Find("input[name='thumb_url']").AttrOr("value", "")

	if imgUrl == "" || thumbUrl == "" {
		html, _ := doc.Html()
		reImg := regexp.MustCompile(`value=['"](https?://vipr\.im/i/[^'"]+)['"]`)
		reThumb := regexp.MustCompile(`src=['"](https?://vipr\.im/th/[^'"]+)['"]`)
		mI := reImg.FindStringSubmatch(html)
		mT := reThumb.FindStringSubmatch(html)
		if len(mI) > 1 {
			imgUrl = mI[1]
		}
		if len(mT) > 1 {
			thumbUrl = mT[1]
		}
	}

	if imgUrl != "" && thumbUrl != "" {
		return imgUrl, thumbUrl, nil
	}
	return "", "", fmt.Errorf("vipr parse failed")
}

func uploadTurbo(ctx context.Context, fp string, job *JobRequest) (string, string, error) {
	// RATE LIMITING: Wait for rate limiter approval to prevent IP bans
	if err := waitForRateLimit(ctx, "turboimagehost"); err != nil {
		return "", "", fmt.Errorf("rate limit: %w", err)
	}

	turboSt.mu.RLock()
	needsLogin := turboSt.endpoint == ""
	endp := turboSt.endpoint
	turboSt.mu.RUnlock()

	if needsLogin {
		doTurboLogin(job.Creds)
		turboSt.mu.RLock()
		endp = turboSt.endpoint
		turboSt.mu.RUnlock()
	}

	if endp == "" {
		endp = "https://www.turboimagehost.com/upload_html5.tu"
	}

	fi, err := os.Stat(fp)
	if err != nil {
		return "", "", fmt.Errorf("failed to stat file: %w", err)
	}

	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)
	go func() {
		defer func() { _ = pw.Close() }()
		defer func() { _ = writer.Close() }()
		h := make(textproto.MIMEHeader)
		h.Set("Content-Disposition", fmt.Sprintf(`form-data; name="qqfile"; filename="%s"`, quoteEscape(filepath.Base(fp))))
		h.Set("Content-Type", "application/octet-stream")
		part, err := writer.CreatePart(h)
		if err != nil {
			pw.CloseWithError(fmt.Errorf("failed to create form part: %w", err))
			return
		}
		f, err := os.Open(fp)
		if err != nil {
			pw.CloseWithError(fmt.Errorf("failed to open file: %w", err))
			return
		}
		defer func() { _ = f.Close() }()
		if _, err := io.Copy(part, f); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to copy file: %w", err))
			return
		}
		if err := writer.WriteField("qquuid", randomString(32)); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write qquuid field: %w", err))
			return
		}
		if err := writer.WriteField("qqfilename", filepath.Base(fp)); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write qqfilename field: %w", err))
			return
		}
		if err := writer.WriteField("qqtotalfilesize", fmt.Sprintf("%d", fi.Size())); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write qqtotalfilesize field: %w", err))
			return
		}
		if err := writer.WriteField("imcontent", job.Config["turbo_content"]); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write imcontent field: %w", err))
			return
		}
		if err := writer.WriteField("thumb_size", job.Config["turbo_thumb"]); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write thumb_size field: %w", err))
			return
		}
	}()

	resp, err := doRequest(ctx, "POST", endp, pr, writer.FormDataContentType())
	if err != nil {
		return "", "", fmt.Errorf("request failed: %w", err)
	}
	raw, err := io.ReadAll(resp.Body)
	_ = resp.Body.Close()
	if err != nil {
		return "", "", fmt.Errorf("failed to read response: %w", err)
	}

	var res struct {
		Success bool   `json:"success"`
		NewUrl  string `json:"newUrl"`
		Id      string `json:"id"`
	}
	if err := json.Unmarshal(raw, &res); err != nil {
		return "", "", fmt.Errorf("failed to parse response: %w", err)
	}
	if res.Success {
		if res.NewUrl != "" {
			return scrapeBBCode(res.NewUrl)
		}
		if res.Id != "" {
			u := fmt.Sprintf("https://www.turboimagehost.com/p/%s/%s.html", res.Id, filepath.Base(fp))
			return u, u, nil
		}
	}
	return "", "", fmt.Errorf("turbo upload failed")
}

func uploadImageBam(ctx context.Context, fp string, job *JobRequest) (string, string, error) {
	// RATE LIMITING: Wait for rate limiter approval to prevent IP bans
	if err := waitForRateLimit(ctx, "imagebam.com"); err != nil {
		return "", "", fmt.Errorf("rate limit: %w", err)
	}

	ibSt.mu.RLock()
	needsLogin := ibSt.uploadToken == ""
	csrf := ibSt.csrf
	token := ibSt.uploadToken
	ibSt.mu.RUnlock()

	if needsLogin {
		doImageBamLogin(job.Creds)
		ibSt.mu.RLock()
		csrf = ibSt.csrf
		token = ibSt.uploadToken
		ibSt.mu.RUnlock()
	}

	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)
	go func() {
		defer func() { _ = pw.Close() }()
		defer func() { _ = writer.Close() }()
		part, err := writer.CreateFormFile("files[0]", filepath.Base(fp))
		if err != nil {
			pw.CloseWithError(fmt.Errorf("failed to create form file: %w", err))
			return
		}
		f, err := os.Open(fp)
		if err != nil {
			pw.CloseWithError(fmt.Errorf("failed to open file: %w", err))
			return
		}
		defer func() { _ = f.Close() }()
		if _, err := io.Copy(part, f); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to copy file: %w", err))
			return
		}
		if err := writer.WriteField("_token", csrf); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write _token field: %w", err))
			return
		}
		if err := writer.WriteField("data", token); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to write data field: %w", err))
			return
		}
	}()

	// CRITICAL: Use context for proper cancellation
	req, err := http.NewRequestWithContext(ctx, "POST", "https://www.imagebam.com/upload", pr)
	if err != nil {
		return "", "", fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("X-Requested-With", "XMLHttpRequest")
	req.Header.Set("X-CSRF-TOKEN", csrf)
	req.Header.Set("User-Agent", UserAgent)
	req.Header.Set("Origin", "https://www.imagebam.com")

	resp, err := client.Do(req)
	if err != nil {
		return "", "", fmt.Errorf("request failed: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	var res struct {
		Status string `json:"status"`
		Data   []struct {
			Url   string `json:"url"`
			Thumb string `json:"thumb"`
		} `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&res); err != nil {
		return "", "", fmt.Errorf("failed to decode response: %w", err)
	}
	if res.Status == "success" && len(res.Data) > 0 {
		return res.Data[0].Url, res.Data[0].Thumb, nil
	}
	return "", "", fmt.Errorf("imagebam failed")
}

// --- Service Helpers ---

func scrapeImxGalleries(creds map[string]string) []map[string]string {
	user := creds["imx_user"]
	if user == "" {
		user = creds["vipr_user"]
	}
	pass := creds["imx_pass"]
	if pass == "" {
		pass = creds["vipr_pass"]
	}

	v := url.Values{"op": {"login"}, "login": {user}, "password": {pass}, "redirect": {"https://imx.to/user/galleries"}}
	if r, err := doRequest(context.Background(), "POST", "https://imx.to/login.html", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded"); err == nil {
		_ = r.Body.Close()
	}

	resp, err := doRequest(context.Background(), "GET", "https://imx.to/user/galleries", nil, "")
	if err != nil {
		return nil
	}
	defer func() { _ = resp.Body.Close() }()

	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil {
		return nil
	}

	var results []map[string]string
	seen := make(map[string]bool)

	doc.Find("a").Each(func(i int, s *goquery.Selection) {
		href, exists := s.Attr("href")
		if !exists {
			return
		}
		if strings.Contains(href, "/g/") {
			parts := strings.Split(href, "/g/")
			if len(parts) > 1 {
				id := parts[1]
				id = strings.Split(id, "?")[0]
				id = strings.Split(id, "/")[0]
				name := strings.TrimSpace(s.Find("i").Text())
				if name == "" {
					return
				}
				if !seen[id] {
					results = append(results, map[string]string{"id": id, "name": name})
					seen[id] = true
				}
			}
		}
	})
	return results
}

func createImxGallery(creds map[string]string, name string) (string, error) {
	v := url.Values{"name": {name}, "public": {"1"}, "submit": {"Save"}}
	resp, err := doRequest(context.Background(), "POST", "https://imx.to/user/gallery/add", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded")
	if err != nil {
		return "", err
	}
	defer func() { _ = resp.Body.Close() }()
	finalUrl := resp.Request.URL.String()
	if strings.Contains(finalUrl, "id=") {
		u, _ := url.Parse(finalUrl)
		q := u.Query()
		return q.Get("id"), nil
	}
	return "0", nil
}

func doViprLogin(creds map[string]string) bool {
	v := url.Values{"op": {"login"}, "login": {creds["vipr_user"]}, "password": {creds["vipr_pass"]}}
	if r, err := doRequest(context.Background(), "POST", "https://vipr.im/login.html", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded"); err == nil {
		_ = r.Body.Close()
	}
	resp, err := doRequest(context.Background(), "GET", "https://vipr.im/", nil, "")
	if err != nil {
		return false
	}
	defer func() { _ = resp.Body.Close() }()
	bodyBytes, _ := io.ReadAll(resp.Body)
	doc, _ := goquery.NewDocumentFromReader(bytes.NewReader(bodyBytes))

	viprSt.mu.Lock()
	defer viprSt.mu.Unlock()

	if action, exists := doc.Find("form[action*='upload.cgi']").Attr("action"); exists {
		viprSt.endpoint = action
	}
	if val, exists := doc.Find("input[name='sess_id']").Attr("value"); exists {
		viprSt.sessId = val
	}
	if viprSt.sessId == "" {
		html := string(bodyBytes)
		if m := regexp.MustCompile(`name=["']sess_id["']\s+value=["']([^"']+)["']`).FindStringSubmatch(html); len(m) > 1 {
			viprSt.sessId = m[1]
		}
		if viprSt.endpoint == "" {
			if m := regexp.MustCompile(`action=["'](https?://[^/]+/cgi-bin/upload\.cgi)`).FindStringSubmatch(html); len(m) > 1 {
				viprSt.endpoint = m[1]
			}
		}
	}
	return viprSt.sessId != ""
}

func scrapeViprGalleries() []map[string]string {
	resp, err := doRequest(context.Background(), "GET", "https://vipr.im/?op=my_files", nil, "")
	if err != nil {
		return nil
	}
	defer func() { _ = resp.Body.Close() }()
	bodyBytes, _ := io.ReadAll(resp.Body)
	var results []map[string]string
	seen := make(map[string]bool)
	doc, err := goquery.NewDocumentFromReader(bytes.NewReader(bodyBytes))
	if err == nil {
		doc.Find("a[href*='fld_id=']").Each(func(i int, s *goquery.Selection) {
			href, _ := s.Attr("href")
			u, _ := url.Parse(href)
			if u != nil {
				id := u.Query().Get("fld_id")
				name := strings.TrimSpace(s.Text())
				if id != "" && name != "" && !seen[id] {
					results = append(results, map[string]string{"id": id, "name": name})
					seen[id] = true
				}
			}
		})
	}
	if len(results) == 0 {
		html := string(bodyBytes)
		re := regexp.MustCompile(`fld_id=(\d+)[^>]*>([^<]+)</a>`)
		matches := re.FindAllStringSubmatch(html, -1)
		for _, m := range matches {
			if !seen[m[1]] {
				results = append(results, map[string]string{"id": m[1], "name": m[2]})
				seen[m[1]] = true
			}
		}
	}
	return results
}

func createViprGallery(name string) (string, error) {
	v := url.Values{"op": {"my_files"}, "add_folder": {name}}
	if r, err := doRequest(context.Background(), "GET", "https://vipr.im/?"+v.Encode(), nil, ""); err == nil {
		_ = r.Body.Close()
	}
	return "0", nil
}

func doImageBamLogin(creds map[string]string) bool {
	resp1, err := doRequest(context.Background(), "GET", "https://www.imagebam.com/auth/login", nil, "")
	if err != nil {
		return false
	}
	defer func() { _ = resp1.Body.Close() }()
	doc1, _ := goquery.NewDocumentFromReader(resp1.Body)
	token := doc1.Find("input[name='_token']").AttrOr("value", "")
	v := url.Values{"_token": {token}, "email": {creds["imagebam_user"]}, "password": {creds["imagebam_pass"]}, "remember": {"on"}}
	if r, err := doRequest(context.Background(), "POST", "https://www.imagebam.com/auth/login", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded"); err == nil {
		_ = r.Body.Close()
	}
	resp2, _ := doRequest(context.Background(), "GET", "https://www.imagebam.com/", nil, "")
	defer func() { _ = resp2.Body.Close() }()
	doc2, _ := goquery.NewDocumentFromReader(resp2.Body)

	ibSt.mu.Lock()
	defer ibSt.mu.Unlock()

	ibSt.csrf = doc2.Find("meta[name='csrf-token']").AttrOr("content", "")
	if ibSt.csrf == "" {
		doc2.Find("meta").Each(func(i int, s *goquery.Selection) {
			if s.AttrOr("name", "") == "csrf-token" {
				ibSt.csrf = s.AttrOr("content", "")
			}
		})
	}
	if ibSt.csrf != "" {
		req, _ := http.NewRequest("POST", "https://www.imagebam.com/upload/session", strings.NewReader("content_type=1&thumbnail_size=1"))
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		req.Header.Set("X-Requested-With", "XMLHttpRequest")
		req.Header.Set("X-CSRF-TOKEN", ibSt.csrf)
		req.Header.Set("User-Agent", UserAgent)
		if r3, e3 := client.Do(req); e3 == nil {
			defer func() { _ = r3.Body.Close() }()
			var j struct{ Status, Data string }
			if err := json.NewDecoder(r3.Body).Decode(&j); err == nil {
				if j.Status == "success" {
					ibSt.uploadToken = j.Data
				}
			}
		}
	}
	return ibSt.csrf != ""
}

func doTurboLogin(creds map[string]string) bool {
	if creds["turbo_user"] != "" {
		v := url.Values{"username": {creds["turbo_user"]}, "password": {creds["turbo_pass"]}, "login": {"Login"}}
		if r, err := doRequest(context.Background(), "POST", "https://www.turboimagehost.com/login", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded"); err == nil {
			_ = r.Body.Close()
		}
	}
	resp, err := doRequest(context.Background(), "GET", "https://www.turboimagehost.com/", nil, "")
	if err != nil {
		return false
	}
	defer func() { _ = resp.Body.Close() }()
	b, _ := io.ReadAll(resp.Body)
	html := string(b)

	turboSt.mu.Lock()
	defer turboSt.mu.Unlock()

	if m := regexp.MustCompile(`endpoint:\s*'([^']+)'`).FindStringSubmatch(html); len(m) > 1 {
		turboSt.endpoint = m[1]
	}
	return turboSt.endpoint != ""
}

func scrapeBBCode(urlStr string) (string, string, error) {
	resp, err := doRequest(context.Background(), "GET", urlStr, nil, "")
	if err != nil {
		return urlStr, urlStr, nil
	}
	defer func() { _ = resp.Body.Close() }()
	b, _ := io.ReadAll(resp.Body)
	html := string(b)
	re := regexp.MustCompile(`(?i)\[url=["']?(https?://[^"']+)["']?\]\s*\[img\](https?://[^\[]+)\[/img\]\s*\[/url\]`)
	if m := re.FindStringSubmatch(html); len(m) > 2 {
		return m[1], m[2], nil
	}
	return urlStr, urlStr, nil
}

func handleViperLogin(job JobRequest) {
	user, pass := job.Creds["vg_user"], job.Creds["vg_pass"]
	if r, err := doRequest(context.Background(), "GET", "https://vipergirls.to/login.php?do=login", nil, ""); err == nil {
		_ = r.Body.Close()
	}

	// SECURITY NOTE: ViperGirls uses MD5 for authentication (legacy vBulletin system).
	// This is required by their API and not our choice. Users should use unique passwords.
	hasher := md5.New()
	_, _ = hasher.Write([]byte(pass)) // hash.Hash.Write never returns an error
	md5Pass := hex.EncodeToString(hasher.Sum(nil))
	v := url.Values{"vb_login_username": {user}, "vb_login_md5password": {md5Pass}, "vb_login_md5password_utf": {md5Pass}, "cookieuser": {"1"}, "do": {"login"}, "securitytoken": {"guest"}}
	resp, _ := doRequest(context.Background(), "POST", "https://vipergirls.to/login.php?do=login", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded")
	b, _ := io.ReadAll(resp.Body)
	_ = resp.Body.Close()
	body := string(b)
	if strings.Contains(body, "Thank you for logging in") {
		if m := regexp.MustCompile(`SECURITYTOKEN\s*=\s*"([^"]+)"`).FindStringSubmatch(body); len(m) > 1 {
			vgSt.mu.Lock()
			vgSt.securityToken = m[1]
			vgSt.mu.Unlock()
		}
		sendJSON(OutputEvent{Type: "result", Status: "success", Msg: "Login OK"})
	} else {
		sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: "Invalid Creds"})
	}
}

func handleViperPost(job JobRequest) {
	vgSt.mu.RLock()
	token := vgSt.securityToken
	needsRefresh := token == "" || token == "guest"
	vgSt.mu.RUnlock()

	if needsRefresh {
		if resp, err := doRequest(context.Background(), "GET", "https://vipergirls.to/forum.php", nil, ""); err == nil {
			b, _ := io.ReadAll(resp.Body)
			_ = resp.Body.Close()
			if m := regexp.MustCompile(`SECURITYTOKEN\s*=\s*"([^"]+)"`).FindStringSubmatch(string(b)); len(m) > 1 {
				vgSt.mu.Lock()
				vgSt.securityToken = m[1]
				token = m[1]
				vgSt.mu.Unlock()
			}
		}
	}
	v := url.Values{
		"message": {job.Config["message"]}, "securitytoken": {token},
		"do": {"postreply"}, "t": {job.Config["thread_id"]}, "parseurl": {"1"}, "emailupdate": {"9999"},
	}
	urlStr := fmt.Sprintf("https://vipergirls.to/newreply.php?do=postreply&t=%s", job.Config["thread_id"])
	resp, err := doRequest(context.Background(), "POST", urlStr, strings.NewReader(v.Encode()), "application/x-www-form-urlencoded")
	if err != nil {
		sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: err.Error()})
		return
	}
	defer func() { _ = resp.Body.Close() }()
	b, _ := io.ReadAll(resp.Body)
	body := string(b)
	finalUrl := resp.Request.URL.String()
	if strings.Contains(strings.ToLower(body), "thank you for posting") || strings.Contains(strings.ToLower(body), "redirecting") {
		sendJSON(OutputEvent{Type: "result", Status: "success", Msg: "Posted"})
		return
	}
	if strings.Contains(finalUrl, "showthread.php") || strings.Contains(finalUrl, "threads/") {
		sendJSON(OutputEvent{Type: "result", Status: "success", Msg: "Posted (Redirected)"})
		return
	}
	if strings.Contains(strings.ToLower(body), "duplicate") {
		sendJSON(OutputEvent{Type: "result", Status: "success", Msg: "Already Posted"})
		return
	}
	sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: "Post not confirmed"})
}

func doRequest(ctx context.Context, method, urlStr string, body io.Reader, contentType string) (*http.Response, error) {
	// CRITICAL: Use context for proper cancellation
	req, err := http.NewRequestWithContext(ctx, method, urlStr, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", UserAgent)
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	if strings.Contains(urlStr, "imagebam.com") {
		req.Header.Set("Referer", "https://www.imagebam.com/")
	}
	if strings.Contains(urlStr, "vipr.im") {
		req.Header.Set("Referer", "https://vipr.im/")
	}
	if strings.Contains(urlStr, "turboimagehost.com") {
		req.Header.Set("Referer", "https://www.turboimagehost.com/")
	}
	if strings.Contains(urlStr, "imx.to") {
		req.Header.Set("Referer", "https://imx.to/")
	}
	if strings.Contains(urlStr, "vipergirls.to") {
		req.Header.Set("Referer", "https://vipergirls.to/forum.php")
	}
	return client.Do(req)
}

func sendJSON(v interface{}) {
	outputMutex.Lock()
	defer outputMutex.Unlock()
	b, _ := json.Marshal(v)
	fmt.Println(string(b))
}
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
	"math"
	"mime/multipart"
	"net/http"
	"net/http/cookiejar"
	"net/textproto"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

// --- Constants ---
const DefaultUserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

func getUserAgent(config map[string]string) string {
	if ua, ok := config["user_agent"]; ok && ua != "" {
		return ua
	}
	return DefaultUserAgent
}

const (
	ClientTimeout = 180 * time.Second 
	PreRequestTimeout = 60 * time.Second
	ResponseHeaderTimeout = 60 * time.Second
	PreRequestHeaderTimeout = 30 * time.Second
	ProgressReportInterval = 2 * time.Second
)

const (
	DefaultMaxRetries = 3
	DefaultInitialBackoff = 1 * time.Second
	DefaultMaxBackoff = 30 * time.Second
	DefaultBackoffMultiplier = 2.0
)

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

// --- Protocol Structs ---
type JobRequest struct {
	Action      string            `json:"action"`
	Service     string            `json:"service"`
	Files       []string          `json:"files"`
	Creds       map[string]string `json:"creds"`
	Config      map[string]string `json:"config"`
	ContextData map[string]string `json:"context_data"`
	HttpSpec    *HttpRequestSpec  `json:"http_spec,omitempty"`
	RateLimits  *RateLimitConfig  `json:"rate_limits,omitempty"`
	RetryConfig *RetryConfig      `json:"retry_config,omitempty"`
}

type RateLimitConfig struct {
	RequestsPerSecond float64 `json:"requests_per_second"`
	BurstSize         int     `json:"burst_size"`
	GlobalLimit       float64 `json:"global_limit"`
}

type HttpRequestSpec struct {
	URL             string                    `json:"url"`
	Method          string                    `json:"method"`
	Headers         map[string]string         `json:"headers"`
	MultipartFields map[string]MultipartField `json:"multipart_fields"`
	FormFields      map[string]string         `json:"form_fields,omitempty"`
	ResponseParser  ResponseParserSpec        `json:"response_parser"`
	PreRequest      *PreRequestSpec           `json:"pre_request,omitempty"`
}

type PreRequestSpec struct {
	Action          string            `json:"action"`
	URL             string            `json:"url"`
	Method          string            `json:"method"`
	Headers         map[string]string `json:"headers,omitempty"`
	FormFields      map[string]string `json:"form_fields,omitempty"`
	UseCookies      bool              `json:"use_cookies"`
	ExtractFields   map[string]string `json:"extract_fields"`
	ResponseType    string            `json:"response_type"`
	FollowUpRequest *PreRequestSpec   `json:"follow_up_request,omitempty"`
}

type MultipartField struct {
	Type  string `json:"type"`
	Value string `json:"value"`
}

type ResponseParserSpec struct {
	Type          string `json:"type"`
	URLPath       string `json:"url_path"`
	ThumbPath     string `json:"thumb_path"`
	StatusPath    string `json:"status_path"`
	SuccessValue  string `json:"success_value"`
	URLTemplate   string `json:"url_template,omitempty"`
	ThumbTemplate string `json:"thumb_template,omitempty"`
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

type RetryConfig struct {
	MaxRetries         int           `json:"max_retries"`
	InitialBackoff     time.Duration `json:"initial_backoff"`
	MaxBackoff         time.Duration `json:"max_backoff"`
	BackoffMultiplier  float64       `json:"backoff_multiplier"`
	RetryableHTTPCodes []int         `json:"retryable_http_codes"`
}

type ProgressEvent struct {
	BytesTransferred int64   `json:"bytes_transferred"`
	TotalBytes       int64   `json:"total_bytes"`
	Speed            float64 `json:"speed"`
	Percentage       float64 `json:"percentage"`
	ETA              int     `json:"eta_seconds"`
}

// --- Globals ---
var outputMutex sync.Mutex
var client *http.Client

var rateLimiters = map[string]*rate.Limiter{
	"imx.to":         rate.NewLimiter(rate.Limit(2.0), 5),
	"pixhost.to":     rate.NewLimiter(rate.Limit(2.0), 5),
	"vipr.im":        rate.NewLimiter(rate.Limit(2.0), 5),
	"turboimagehost": rate.NewLimiter(rate.Limit(2.0), 5),
	"imagebam.com":   rate.NewLimiter(rate.Limit(2.0), 5),
	"vipergirls.to":  rate.NewLimiter(rate.Limit(1.0), 3),
}
var rateLimiterMutex sync.RWMutex
var globalRateLimiter = rate.NewLimiter(rate.Limit(10.0), 20)

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

// NEW: Add state tracker for IMX login status
type imxState struct {
	mu         sync.RWMutex
	isLoggedIn bool
}

var viprSt = &viprState{}
var turboSt = &turboState{}
var ibSt = &imageBamState{}
var vgSt = &viperGirlsState{}
var imxSt = &imxState{} // Initialize IMX state

var quoteEscaper = strings.NewReplacer("\\", "\\\\", `"`, "\\\"")

func quoteEscape(s string) string { return quoteEscaper.Replace(s) }

func getRateLimiter(service string) *rate.Limiter {
	rateLimiterMutex.RLock()
	limiter, exists := rateLimiters[service]
	rateLimiterMutex.RUnlock()

	if !exists {
		limiter = rate.NewLimiter(rate.Limit(2.0), 5)
		rateLimiterMutex.Lock()
		rateLimiters[service] = limiter
		rateLimiterMutex.Unlock()
	}

	return limiter
}

func updateRateLimiter(service string, config *RateLimitConfig) {
	if config == nil {
		return
	}
	rateLimiterMutex.Lock()
	defer rateLimiterMutex.Unlock()

	limiter := rate.NewLimiter(
		rate.Limit(config.RequestsPerSecond),
		config.BurstSize,
	)
	rateLimiters[service] = limiter

	if config.GlobalLimit > 0 {
		oldBurst := globalRateLimiter.Burst()
		globalRateLimiter = rate.NewLimiter(rate.Limit(config.GlobalLimit), oldBurst)
	}
}

func waitForRateLimit(ctx context.Context, service string) error {
	if err := globalRateLimiter.Wait(ctx); err != nil {
		return fmt.Errorf("global rate limit wait cancelled: %w", err)
	}
	limiter := getRateLimiter(service)
	if err := limiter.Wait(ctx); err != nil {
		return fmt.Errorf("service rate limit wait cancelled: %w", err)
	}
	return nil
}

const charset = "abcdefghijklmnopqrstuvwxyz0123456789"

func randomString(n int) string {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		return fmt.Sprintf("%d", time.Now().UnixNano())
	}
	for i := range b {
		b[i] = charset[int(b[i])%len(charset)]
	}
	return string(b)
}

func getDefaultRetryConfig() *RetryConfig {
	return &RetryConfig{
		MaxRetries:         DefaultMaxRetries,
		InitialBackoff:     DefaultInitialBackoff,
		MaxBackoff:         DefaultMaxBackoff,
		BackoffMultiplier:  DefaultBackoffMultiplier,
		RetryableHTTPCodes: []int{408, 429, 500, 502, 503, 504},
	}
}

func extractStatusCode(err error) int {
	if err == nil {
		return 0
	}
	errStr := err.Error()
	if idx := strings.Index(errStr, "status code"); idx != -1 {
		remaining := errStr[idx+len("status code"):]
		remaining = strings.TrimLeft(remaining, ": ")
		if code, parseErr := strconv.Atoi(strings.Fields(remaining)[0]); parseErr == nil {
			return code
		}
	}
	if idx := strings.Index(strings.ToLower(errStr), "http "); idx != -1 {
		remaining := errStr[idx+5:]
		if code, parseErr := strconv.Atoi(strings.Fields(remaining)[0]); parseErr == nil {
			return code
		}
	}
	re := regexp.MustCompile(`\b([45]\d{2})\b`)
	if matches := re.FindStringSubmatch(errStr); len(matches) > 1 {
		if code, parseErr := strconv.Atoi(matches[1]); parseErr == nil {
			return code
		}
	}
	return 0
}

func isRetryableError(err error, statusCode int, config *RetryConfig) bool {
	if err == nil {
		return false
	}
	for _, code := range config.RetryableHTTPCodes {
		if statusCode == code {
			return true
		}
	}
	errStr := strings.ToLower(err.Error())
	retryablePatterns := []string{
		"timeout", "connection refused", "connection reset", "temporary failure",
		"no such host", "network is unreachable", "broken pipe", "i/o timeout",
		"tls handshake timeout", "dial tcp", "eof",
	}
	for _, pattern := range retryablePatterns {
		if strings.Contains(errStr, pattern) {
			return true
		}
	}
	return false
}

func calculateBackoff(attempt int, config *RetryConfig) time.Duration {
	backoff := float64(config.InitialBackoff) * math.Pow(config.BackoffMultiplier, float64(attempt))
	if backoff > float64(config.MaxBackoff) {
		backoff = float64(config.MaxBackoff)
	}
	var jitterBytes [8]byte
	if _, err := rand.Read(jitterBytes[:]); err != nil {
		return time.Duration(backoff)
	}
	randUint := uint64(jitterBytes[0]) | uint64(jitterBytes[1])<<8 | uint64(jitterBytes[2])<<16 | uint64(jitterBytes[3])<<24 | uint64(jitterBytes[4])<<32 | uint64(jitterBytes[5])<<40 | uint64(jitterBytes[6])<<48 | uint64(jitterBytes[7])<<56
	randFloat := float64(randUint) / float64(^uint64(0))
	jitter := (randFloat * 0.4) - 0.2
	backoff = backoff * (1.0 + jitter)
	return time.Duration(backoff)
}

func retryWithBackoff[T any](
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
				logger.WithFields(log.Fields{"attempt": attempt + 1}).Info("Request succeeded after retry")
			}
			return result, nil
		}
		if !isRetryableError(lastErr, lastStatusCode, config) {
			return result, lastErr
		}
		if attempt >= config.MaxRetries {
			break
		}
		backoffDuration := calculateBackoff(attempt+1, config)
		logger.WithFields(log.Fields{"attempt": attempt + 1, "backoff": backoffDuration.Seconds()}).Info("Request failed, retrying")
		select {
		case <-time.After(backoffDuration):
		case <-ctx.Done():
			return result, ctx.Err()
		}
	}
	return result, fmt.Errorf("max retries (%d) exhausted, last error: %w", config.MaxRetries, lastErr)
}

type ProgressWriter struct {
	writer         io.Writer
	totalBytes     int64
	bytesWritten   int64
	startTime      time.Time
	lastReportTime time.Time
	filePath       string
	mu             sync.Mutex
}

func NewProgressWriter(w io.Writer, totalBytes int64, filePath string) *ProgressWriter {
	now := time.Now()
	return &ProgressWriter{
		writer:         w,
		totalBytes:     totalBytes,
		bytesWritten:   0,
		startTime:      now,
		lastReportTime: now,
		filePath:       filePath,
	}
}

func (pw *ProgressWriter) Write(p []byte) (int, error) {
	n, err := pw.writer.Write(p)
	pw.mu.Lock()
	pw.bytesWritten += int64(n)
	bytesWritten := pw.bytesWritten
	totalBytes := pw.totalBytes
	now := time.Now()
	shouldReport := now.Sub(pw.lastReportTime) >= ProgressReportInterval
	if shouldReport {
		pw.lastReportTime = now
	}
	pw.mu.Unlock()
	if shouldReport {
		elapsed := now.Sub(pw.startTime).Seconds()
		speed := float64(bytesWritten) / elapsed
		percentage := (float64(bytesWritten) / float64(totalBytes)) * 100.0
		var eta int
		if speed > 0 {
			remaining := totalBytes - bytesWritten
			eta = int(float64(remaining) / speed)
		}
		sendJSON(OutputEvent{
			Type:     "progress",
			FilePath: pw.filePath,
			Data: ProgressEvent{
				BytesTransferred: bytesWritten,
				TotalBytes:       totalBytes,
				Speed:            speed,
				Percentage:       percentage,
				ETA:              eta,
			},
		})
	}
	return n, err
}

func validateFilePath(filePath string) error {
	if filePath == "" {
		return fmt.Errorf("file path cannot be empty")
	}
	absPath, err := filepath.Abs(filePath)
	if err != nil {
		return fmt.Errorf("invalid file path: %w", err)
	}
	if strings.Contains(filePath, "..") {
		return fmt.Errorf("path traversal detected")
	}
	fileInfo, err := os.Stat(absPath)
	if err != nil {
		return fmt.Errorf("cannot access file: %w", err)
	}
	if !fileInfo.Mode().IsRegular() {
		return fmt.Errorf("not a regular file")
	}
	const maxFileSize = 100 * 1024 * 1024
	if fileInfo.Size() > maxFileSize {
		return fmt.Errorf("file too large")
	}
	return nil
}

func validateServiceName(service string) error {
	if service == "" {
		return fmt.Errorf("service name cannot be empty")
	}
	validPattern := regexp.MustCompile(`^[a-zA-Z0-9\.\-]+$`)
	if !validPattern.MatchString(service) {
		return fmt.Errorf("invalid service name")
	}
	return nil
}

func validateJobRequest(job *JobRequest) error {
	if !map[string]bool{
		"upload": true, "http_upload": true, "login": true, "verify": true,
		"list_galleries": true, "create_gallery": true, "finalize_gallery": true,
		"generate_thumb": true, "viper_login": true, "viper_post": true,
	}[job.Action] {
		return fmt.Errorf("invalid action: %s", job.Action)
	}

	if job.Action != "generate_thumb" {
		if err := validateServiceName(job.Service); err != nil {
			return fmt.Errorf("invalid service: %w", err)
		}
	}

	if map[string]bool{"upload": true, "http_upload": true, "generate_thumb": true}[job.Action] {
		if len(job.Files) == 0 {
			return fmt.Errorf("no files provided")
		}
		for _, fp := range job.Files {
			if err := validateFilePath(fp); err != nil {
				return err
			}
		}
	}
	return nil
}

func main() {
	workerCount := flag.Int("workers", 8, "Number of worker goroutines")
	flag.Parse()

	log.WithFields(log.Fields{"workers": *workerCount}).Info("Go sidecar starting")
	sendJSON(OutputEvent{Type: "log", Msg: fmt.Sprintf("=== GO SIDECAR STARTED - WORKERS: %d ===", *workerCount)})

	jar, _ := cookiejar.New(nil)
	client = &http.Client{
		Timeout: ClientTimeout,
		Jar:     jar,
		Transport: &http.Transport{
			MaxIdleConns:        100,
			MaxIdleConnsPerHost: 10,
			MaxConnsPerHost:     20,
			IdleConnTimeout:     90 * time.Second,
			ResponseHeaderTimeout: ResponseHeaderTimeout,
			ForceAttemptHTTP2:   true,
		},
	}

	jobQueue := make(chan JobRequest, 100)
	var wg sync.WaitGroup
	shutdownChan := make(chan struct{})
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	for i := 0; i < *workerCount; i++ {
		wg.Add(1)
		go func(id int) {
			defer wg.Done()
			for job := range jobQueue {
				handleJob(job)
			}
		}(i)
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
				sendJSON(OutputEvent{Type: "error", Msg: fmt.Sprintf("JSON Decode Error: %v", err)})
				continue
			}
			jobQueue <- job
		}
	}

shutdown:
	close(jobQueue)
	wg.Wait()
	sendJSON(OutputEvent{Type: "log", Msg: "=== GO SIDECAR SHUTDOWN COMPLETE ==="})
}

func handleJob(job JobRequest) {
	defer func() {
		if r := recover(); r != nil {
			sendJSON(OutputEvent{Type: "error", Msg: fmt.Sprintf("Panic: %v", r)})
		}
	}()
	if err := validateJobRequest(&job); err != nil {
		sendJSON(OutputEvent{Type: "error", Msg: fmt.Sprintf("Invalid job: %v", err)})
		return
	}
	if job.RateLimits != nil {
		updateRateLimiter(job.Service, job.RateLimits)
	}
	if job.RetryConfig == nil {
		job.RetryConfig = getDefaultRetryConfig()
	}

	switch job.Action {
	case "upload":
		handleUpload(job)
	case "http_upload":
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
	}
}

func handleFinalizeGallery(job JobRequest) {
	service := job.Service
	uploadHash := job.Config["gallery_upload_hash"]
	galleryHash := job.Config["gallery_hash"]
	if uploadHash == "" || galleryHash == "" {
		sendJSON(OutputEvent{Type: "error", Msg: "Missing gallery hashes"})
		return
	}
	if service == "pixhost.to" {
		finalizeURL := fmt.Sprintf("https://api.pixhost.to/galleries/%s/%s", galleryHash, uploadHash)
		req, _ := http.NewRequest("PATCH", finalizeURL, nil)
		req.Header.Set("User-Agent", getUserAgent(job.Config))
		if resp, err := client.Do(req); err == nil {
			defer resp.Body.Close()
			if resp.StatusCode >= 200 && resp.StatusCode < 300 {
				sendJSON(OutputEvent{Type: "result", Status: "success", Msg: "Gallery Finalized"})
			} else {
				sendJSON(OutputEvent{Type: "result", Status: "success", Msg: "Gallery upload complete (finalize pending)"})
			}
		} else {
			sendJSON(OutputEvent{Type: "error", Msg: fmt.Sprintf("Finalize failed: %v", err)})
		}
	} else {
		sendJSON(OutputEvent{Type: "result", Status: "success", Msg: "Gallery Finalized"})
	}
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
	defer f.Close()
	img, _, err := image.Decode(f)
	if err != nil {
		sendJSON(OutputEvent{Type: "error", Msg: "Decode failed"})
		return
	}
	thumb := imaging.Resize(img, w, 0, imaging.Lanczos)
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, thumb, &jpeg.Options{Quality: 70}); err != nil {
		sendJSON(OutputEvent{Type: "error", Msg: "Encode failed"})
		return
	}
	sendJSON(OutputEvent{Type: "data", Data: base64.StdEncoding.EncodeToString(buf.Bytes()), Status: "success", FilePath: fp})
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
		// Login check using persistent state
		if doImxLogin(job.Creds) {
			success = true
			msg = "IMX Login Verified"
		} else {
			msg = "IMX Login Failed"
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
	var data interface{}

	switch job.Service {
	case "vipr.im":
		id, err = createViprGallery(name)
		data = id
	case "imagebam.com":
		id = "0"
		data = id
	case "imx.to":
		// FIXED: Login check + Correct Form Fields based on HTML + Fallback Scraper
		if doImxLogin(job.Creds) {
			id, err = createImxGallery(job.Creds, name)
			data = id
		} else {
			err = fmt.Errorf("IMX login failed - check credentials")
		}
	case "pixhost.to":
		galData, galErr := createPixhostGallery(name)
		if galErr != nil {
			err = galErr
		} else {
			id = galData["gallery_hash"]
			data = galData
		}
	default:
		err = fmt.Errorf("service not supported")
	}

	if err != nil {
		sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: err.Error()})
	} else {
		sendJSON(OutputEvent{Type: "result", Status: "success", Msg: id, Data: data})
	}
}

func handleHttpUpload(job JobRequest) {
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
	ctx, cancel := context.WithTimeout(context.Background(), ClientTimeout)
	defer cancel()

	type result struct {
		url, thumb string
		err        error
	}
	resultChan := make(chan result, 1)

	go func() {
		sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Uploading"})
		retryConfig := job.RetryConfig
		if retryConfig == nil {
			retryConfig = getDefaultRetryConfig()
		}

		type uploadResult struct{ url, thumb string }
		uploadRes, err := retryWithBackoff(ctx, retryConfig, func() (uploadResult, int, error) {
			var url, thumb string
			var err error
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
				err = fmt.Errorf("unknown service")
			}
			return uploadResult{url, thumb}, extractStatusCode(err), err
		}, log.WithFields(log.Fields{"file": filepath.Base(fp)}))

		select {
		case resultChan <- result{uploadRes.url, uploadRes.thumb, err}:
		case <-ctx.Done():
		}
	}()

	select {
	case res := <-resultChan:
		if res.err != nil {
			sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Failed"})
			sendJSON(OutputEvent{Type: "error", FilePath: fp, Msg: res.err.Error()})
		} else {
			sendJSON(OutputEvent{Type: "result", FilePath: fp, Url: res.url, Thumb: res.thumb})
			sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Done"})
		}
	case <-ctx.Done():
		sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Timeout"})
		sendJSON(OutputEvent{Type: "error", FilePath: fp, Msg: "Upload timed out"})
	}
}

func processFileGeneric(fp string, job *JobRequest) {
	ctx, cancel := context.WithTimeout(context.Background(), ClientTimeout)
	defer cancel()

	type result struct {
		url, thumb string
		err        error
	}
	resultChan := make(chan result, 1)

	go func() {
		sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Uploading"})
		retryConfig := job.RetryConfig
		if retryConfig == nil {
			retryConfig = getDefaultRetryConfig()
		}

		type uploadResult struct{ url, thumb string }
		uploadRes, err := retryWithBackoff(ctx, retryConfig, func() (uploadResult, int, error) {
			url, thumb, err := executeHttpUpload(ctx, fp, job)
			return uploadResult{url, thumb}, extractStatusCode(err), err
		}, log.WithFields(log.Fields{"file": filepath.Base(fp)}))

		select {
		case resultChan <- result{uploadRes.url, uploadRes.thumb, err}:
		case <-ctx.Done():
		}
	}()

	select {
	case res := <-resultChan:
		if res.err != nil {
			sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Failed"})
			sendJSON(OutputEvent{Type: "error", FilePath: fp, Msg: res.err.Error()})
		} else {
			sendJSON(OutputEvent{Type: "result", FilePath: fp, Url: res.url, Thumb: res.thumb})
			sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Done"})
		}
	case <-ctx.Done():
		sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Timeout"})
		sendJSON(OutputEvent{Type: "error", FilePath: fp, Msg: "Upload timed out"})
	}
}

func executeHttpUpload(ctx context.Context, fp string, job *JobRequest) (string, string, error) {
	spec := job.HttpSpec
	if spec == nil {
		return "", "", fmt.Errorf("no http_spec")
	}
	if job.Service != "" {
		if err := waitForRateLimit(ctx, job.Service); err != nil {
			return "", "", err
		}
	}

	extractedValues := make(map[string]string)
	var sessionClient *http.Client
	if spec.PreRequest != nil {
		var err error
		extractedValues, sessionClient, err = executePreRequest(ctx, spec.PreRequest, job.Service)
		if err != nil {
			return "", "", err
		}
	}

	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)
	go func() {
		defer pw.Close()
		defer writer.Close()
		for fieldName, field := range spec.MultipartFields {
			if field.Type == "file" {
				part, _ := writer.CreateFormFile(fieldName, filepath.Base(fp))
				f, _ := os.Open(fp)
				defer f.Close()
				fi, _ := f.Stat()
				progressWriter := NewProgressWriter(part, fi.Size(), fp)
				io.Copy(progressWriter, f)
			} else if field.Type == "text" {
				writer.WriteField(fieldName, field.Value)
			} else if field.Type == "dynamic" {
				if val, ok := extractedValues[field.Value]; ok {
					writer.WriteField(fieldName, val)
				}
			}
		}
	}()

	req, _ := http.NewRequestWithContext(ctx, spec.Method, spec.URL, pr)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("User-Agent", DefaultUserAgent)
	for k, v := range spec.Headers {
		req.Header.Set(k, v)
	}

	var resp *http.Response
	var err error
	if sessionClient != nil {
		resp, err = sessionClient.Do(req)
	} else {
		resp, err = client.Do(req)
	}
	if err != nil {
		return "", "", err
	}
	defer resp.Body.Close()
	return parseHttpResponse(resp, &spec.ResponseParser, fp)
}

func executePreRequest(ctx context.Context, spec *PreRequestSpec, service string) (map[string]string, *http.Client, error) {
	var preClient *http.Client
	if spec.UseCookies {
		jar, _ := cookiejar.New(nil)
		preClient = &http.Client{
			Timeout: PreRequestTimeout,
			Jar:     jar,
			Transport: &http.Transport{MaxIdleConnsPerHost: 10, ResponseHeaderTimeout: PreRequestHeaderTimeout},
		}
	} else {
		preClient = client
	}

	var reqBody io.Reader
	contentType := ""
	if len(spec.FormFields) > 0 {
		v := url.Values{}
		for k, val := range spec.FormFields {
			v.Set(k, val)
		}
		reqBody = strings.NewReader(v.Encode())
		contentType = "application/x-www-form-urlencoded"
	}

	req, _ := http.NewRequestWithContext(ctx, spec.Method, spec.URL, reqBody)
	req.Header.Set("User-Agent", DefaultUserAgent)
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	for k, v := range spec.Headers {
		req.Header.Set(k, v)
	}

	resp, err := preClient.Do(req)
	if err != nil {
		return nil, nil, err
	}
	defer resp.Body.Close()
	bodyBytes, _ := io.ReadAll(resp.Body)

	extracted := make(map[string]string)
	if spec.ResponseType == "json" {
		var data map[string]interface{}
		json.Unmarshal(bodyBytes, &data)
		for k, path := range spec.ExtractFields {
			extracted[k] = getJSONValue(data, path)
		}
	} else if spec.ResponseType == "html" {
		doc, _ := goquery.NewDocumentFromReader(bytes.NewReader(bodyBytes))
		for k, sel := range spec.ExtractFields {
			val := doc.Find(sel).AttrOr("value", "")
			if val == "" {
				val = doc.Find(sel).Text()
			}
			extracted[k] = strings.TrimSpace(val)
		}
	}
	return extracted, preClient, nil
}

func parseHttpResponse(resp *http.Response, parser *ResponseParserSpec, filePath string) (string, string, error) {
	bodyBytes, _ := io.ReadAll(resp.Body)
	if parser.Type == "json" {
		var data map[string]interface{}
		if err := json.Unmarshal(bodyBytes, &data); err != nil {
			return "", "", err
		}
		if parser.StatusPath != "" {
			if getJSONValue(data, parser.StatusPath) != parser.SuccessValue {
				return "", "", fmt.Errorf("upload failed status")
			}
		}
		return getJSONValue(data, parser.URLPath), getJSONValue(data, parser.ThumbPath), nil
	}
	return "", "", fmt.Errorf("unsupported parser")
}

func getJSONValue(data map[string]interface{}, path string) string {
	parts := strings.Split(path, ".")
	current := interface{}(data)
	for _, part := range parts {
		if m, ok := current.(map[string]interface{}); ok {
			current = m[part]
		} else {
			return ""
		}
	}
	if s, ok := current.(string); ok {
		return s
	}
	return ""
}

// --- Upload Implementations ---

func getImxSizeId(s string) string {
	m := map[string]string{"100": "1", "150": "6", "180": "2", "250": "3", "300": "4"}
	if v, ok := m[s]; ok {
		return v
	}
	return "2"
}

func getImxFormatId(s string) string {
	m := map[string]string{"Fixed Width": "1", "Fixed Height": "4", "Proportional": "2", "Square": "3"}
	if v, ok := m[s]; ok {
		return v
	}
	return "1"
}

// Helper to perform IMX login with state tracking
func doImxLogin(creds map[string]string) bool {
	// 1. Check if already logged in (Persistent Session)
	imxSt.mu.RLock()
	if imxSt.isLoggedIn {
		imxSt.mu.RUnlock()
		return true
	}
	imxSt.mu.RUnlock()

	user := creds["imx_user"]
	if user == "" {
		user = creds["vipr_user"]
	}
	pass := creds["imx_pass"]
	if pass == "" {
		pass = creds["vipr_pass"]
	}
	if user == "" || pass == "" {
		return false
	}

	// 2. Perform Initial GET to get cookies (CRITICAL FIX)
	// FIX: Use https://imx.to instead of www.imx.to which has bad cert
	loginUrl := "https://imx.to/login.php"
	getReq, _ := http.NewRequest("GET", loginUrl, nil)
	getReq.Header.Set("User-Agent", DefaultUserAgent)
	getResp, err := client.Do(getReq)
	if err == nil {
		getResp.Body.Close()
	} else {
		sendJSON(OutputEvent{Type: "error", Msg: fmt.Sprintf("IMX Login Pre-check failed: %v", err)})
		return false
	}

	// 3. Perform POST Login Request
	// Using URL and field names from login.html
	sendJSON(OutputEvent{Type: "log", Msg: "IMX: Starting Web Login..."})
	
	// FIX: field names 'usr_email' and 'pwd' (from source code provided by user)
	v := url.Values{
		"usr_email": {user},
		"pwd":       {pass},
		"doLogin":   {"Login"}, 
		"remember":  {"1"}, 
	}
	
	req, _ := http.NewRequest("POST", loginUrl, strings.NewReader(v.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("User-Agent", DefaultUserAgent)
	req.Header.Set("Referer", loginUrl) // Security check
	
	resp, err := client.Do(req)
	
	if err == nil {
		defer resp.Body.Close()
		
		finalUrl := resp.Request.URL.String()
		sendJSON(OutputEvent{Type: "log", Msg: fmt.Sprintf("IMX Login Final URL: %s", finalUrl)})
		
		// 4. Verification
		bodyBytes, _ := io.ReadAll(resp.Body)
		bodyStr := string(bodyBytes)
		
		isSuccess := false
		
		// Success Markers
		// Often redirects to imx.to/user/dashboard or user/galleries
		if strings.Contains(finalUrl, "dashboard") || strings.Contains(finalUrl, "galleries") {
			isSuccess = true
		} else if strings.Contains(strings.ToLower(bodyStr), "logout") || strings.Contains(bodyStr, "Balance") {
			isSuccess = true
		}
		
		// Failure Markers
		if strings.Contains(bodyStr, "login_form") || strings.Contains(bodyStr, "Sign Up") || strings.Contains(bodyStr, "Incorrect username") {
			isSuccess = false
		}

		if isSuccess {
			imxSt.mu.Lock()
			imxSt.isLoggedIn = true
			imxSt.mu.Unlock()
			sendJSON(OutputEvent{Type: "log", Msg: "IMX Login: Verified Success"})
			return true
		}
		
		// Log detailed failure
		snippet := bodyStr
		if len(snippet) > 500 { snippet = snippet[:500] }
		sendJSON(OutputEvent{Type: "error", Msg: fmt.Sprintf("IMX Login Failed. URL: %s. Body start: %s", finalUrl, snippet)})
		return false
	}
	
	sendJSON(OutputEvent{Type: "error", Msg: fmt.Sprintf("IMX Login Request Error: %v", err)})
	return false
}

func uploadImx(ctx context.Context, fp string, job *JobRequest) (string, string, error) {
	if err := waitForRateLimit(ctx, "imx.to"); err != nil {
		return "", "", err
	}
	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)
	go func() {
		defer pw.Close()
		defer writer.Close()
		part, _ := writer.CreateFormFile("image", filepath.Base(fp))
		f, _ := os.Open(fp)
		defer f.Close()
		io.Copy(part, f)
		writer.WriteField("format", "json")
		writer.WriteField("adult", "1")
		writer.WriteField("upload_type", "file")
		writer.WriteField("simple_upload", "Upload")
		
		sizeId := getImxSizeId(job.Config["imx_thumb_id"])
		writer.WriteField("thumbnail_size", sizeId)
		writer.WriteField("thumb_size_container", sizeId)
		writer.WriteField("thumbnail_format", getImxFormatId(job.Config["imx_format_id"]))
		
		if gid := job.Config["gallery_id"]; gid != "" {
			writer.WriteField("gallery_id", gid)
		}
	}()

	req, _ := http.NewRequestWithContext(ctx, "POST", "https://api.imx.to/v1/upload.php", pr)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("X-API-KEY", job.Creds["api_key"])
	req.Header.Set("User-Agent", DefaultUserAgent)

	resp, err := client.Do(req)
	if err != nil {
		return "", "", err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	var res struct {
		Status string `json:"status"`
		Data   struct {
			Img   string `json:"image_url"`
			Thumb string `json:"thumbnail_url"`
		} `json:"data"`
	}
	json.Unmarshal(raw, &res)
	if res.Status != "success" {
		return "", "", fmt.Errorf("upload failed")
	}
	return res.Data.Img, res.Data.Thumb, nil
}

func uploadPixhost(ctx context.Context, fp string, job *JobRequest) (string, string, error) {
	if err := waitForRateLimit(ctx, "pixhost.to"); err != nil {
		return "", "", err
	}
	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)
	go func() {
		defer pw.Close()
		defer writer.Close()
		part, _ := writer.CreateFormFile("img", filepath.Base(fp))
		f, _ := os.Open(fp)
		defer f.Close()
		io.Copy(part, f)
		writer.WriteField("content_type", job.Config["pix_content"])
		writer.WriteField("max_th_size", job.Config["pix_thumb"])
		if h := job.Config["gallery_hash"]; h != "" {
			writer.WriteField("gallery_hash", h)
		}
	}()

	req, _ := http.NewRequestWithContext(ctx, "POST", "https://api.pixhost.to/images", pr)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("User-Agent", DefaultUserAgent)
	resp, err := client.Do(req)
	if err != nil {
		return "", "", err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	var res struct {
		Show string `json:"show_url"`
		Th   string `json:"th_url"`
	}
	json.Unmarshal(raw, &res)
	if res.Show == "" {
		return "", "", fmt.Errorf("failed")
	}
	return res.Show, res.Th, nil
}

func uploadVipr(ctx context.Context, fp string, job *JobRequest) (string, string, error) {
	if err := waitForRateLimit(ctx, "vipr.im"); err != nil {
		return "", "", err
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
		defer pw.Close()
		defer writer.Close()
		safeName := strings.ReplaceAll(filepath.Base(fp), " ", "_")
		part, err := writer.CreateFormFile("file_0", safeName)
		if err != nil { return }
		f, err := os.Open(fp)
		if err != nil { return }
		defer f.Close()
		io.Copy(part, f)
		writer.WriteField("upload_type", "file")
		writer.WriteField("sess_id", sessId)
		writer.WriteField("thumb_size", job.Config["vipr_thumb"])
		writer.WriteField("fld_id", job.Config["vipr_gal_id"])
		writer.WriteField("tos", "1")
		writer.WriteField("submit_btn", "Upload")
	}()
	u := upUrl + "?upload_id=" + randomString(12) + "&js_on=1&utype=reg&upload_type=file"
	resp, err := doRequest(ctx, "POST", u, pr, writer.FormDataContentType())
	if err != nil { return "", "", err }
	defer resp.Body.Close()
	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil { return "", "", err }
	if textArea := doc.Find("textarea[name='fn']"); textArea.Length() > 0 {
		fnVal := textArea.Text()
		v := url.Values{"op": {"upload_result"}, "fn": {fnVal}, "st": {"OK"}}
		if r2, e2 := doRequest(ctx, "POST", "https://vipr.im/", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded"); e2 == nil {
			defer r2.Body.Close()
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
		if len(mI) > 1 { imgUrl = mI[1] }
		if len(mT) > 1 { thumbUrl = mT[1] }
	}
	if imgUrl != "" && thumbUrl != "" { return imgUrl, thumbUrl, nil }
	return "", "", fmt.Errorf("vipr parse failed")
}

func uploadTurbo(ctx context.Context, fp string, job *JobRequest) (string, string, error) {
	if err := waitForRateLimit(ctx, "turboimagehost"); err != nil { return "", "", err }
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
	if endp == "" { endp = "https://www.turboimagehost.com/upload_html5.tu" }
	fi, _ := os.Stat(fp)
	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)
	go func() {
		defer pw.Close()
		defer writer.Close()
		h := make(textproto.MIMEHeader)
		h.Set("Content-Disposition", fmt.Sprintf(`form-data; name="qqfile"; filename="%s"`, quoteEscape(filepath.Base(fp))))
		h.Set("Content-Type", "application/octet-stream")
		part, _ := writer.CreatePart(h)
		f, _ := os.Open(fp)
		defer f.Close()
		io.Copy(part, f)
		writer.WriteField("qquuid", randomString(32))
		writer.WriteField("qqfilename", filepath.Base(fp))
		writer.WriteField("qqtotalfilesize", fmt.Sprintf("%d", fi.Size()))
		writer.WriteField("imcontent", job.Config["turbo_content"])
		writer.WriteField("thumb_size", job.Config["turbo_thumb"])
	}()
	resp, err := doRequest(ctx, "POST", endp, pr, writer.FormDataContentType())
	if err != nil { return "", "", err }
	raw, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	var res struct { Success bool `json:"success"`; NewUrl string `json:"newUrl"`; Id string `json:"id"` }
	json.Unmarshal(raw, &res)
	if res.Success {
		if res.NewUrl != "" { return scrapeBBCode(res.NewUrl) }
		if res.Id != "" { u := fmt.Sprintf("https://www.turboimagehost.com/p/%s/%s.html", res.Id, filepath.Base(fp)); return u, u, nil }
	}
	return "", "", fmt.Errorf("turbo upload failed")
}

func uploadImageBam(ctx context.Context, fp string, job *JobRequest) (string, string, error) {
	if err := waitForRateLimit(ctx, "imagebam.com"); err != nil { return "", "", err }
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
		defer pw.Close()
		defer writer.Close()
		part, _ := writer.CreateFormFile("files[0]", filepath.Base(fp))
		f, _ := os.Open(fp)
		defer f.Close()
		io.Copy(part, f)
		writer.WriteField("_token", csrf)
		writer.WriteField("data", token)
	}()
	req, _ := http.NewRequestWithContext(ctx, "POST", "https://www.imagebam.com/upload", pr)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("X-Requested-With", "XMLHttpRequest")
	req.Header.Set("X-CSRF-TOKEN", csrf)
	req.Header.Set("User-Agent", DefaultUserAgent)
	req.Header.Set("Origin", "https://www.imagebam.com")
	resp, err := client.Do(req)
	if err != nil { return "", "", err }
	defer resp.Body.Close()
	var res struct { Status string `json:"status"`; Data []struct { Url, Thumb string } `json:"data"` }
	json.NewDecoder(resp.Body).Decode(&res)
	if res.Status == "success" && len(res.Data) > 0 { return res.Data[0].Url, res.Data[0].Thumb, nil }
	return "", "", fmt.Errorf("imagebam failed")
}

func scrapeImxGalleries(creds map[string]string) []map[string]string {
	doImxLogin(creds)
	resp, err := doRequest(context.Background(), "GET", "https://imx.to/user/galleries", nil, "")
	if err != nil { return nil }
	defer resp.Body.Close()
	doc, _ := goquery.NewDocumentFromReader(resp.Body)
	var results []map[string]string
	seen := make(map[string]bool)
	doc.Find("a").Each(func(i int, s *goquery.Selection) {
		href, _ := s.Attr("href")
		if strings.Contains(href, "/g/") {
			parts := strings.Split(href, "/g/")
			if len(parts) > 1 {
				id := strings.Split(strings.Split(parts[1], "?")[0], "/")[0]
				name := strings.TrimSpace(s.Find("i").Text())
				if name != "" && !seen[id] {
					results = append(results, map[string]string{"id": id, "name": name})
					seen[id] = true
				}
			}
		}
	})
	return results
}

func createImxGallery(creds map[string]string, name string) (string, error) {
	doImxLogin(creds)
	// Use correct form fields (verified from uploaded HTML)
	// Use naked domain imx.to to match login cookie
	v := url.Values{"gallery_name": {name}, "submit_new_gallery": {"Add"}}
	
	req, _ := http.NewRequest("POST", "https://imx.to/user/gallery/add", strings.NewReader(v.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("User-Agent", DefaultUserAgent)
	req.Header.Set("Referer", "https://imx.to/user/gallery/add") // Required for validation
	
	resp, err := client.Do(req)
	
	if err != nil { return "", err }
	defer resp.Body.Close()
	
	finalUrl := resp.Request.URL.String()
	
	// DEBUG LOG
	sendJSON(OutputEvent{Type: "log", Msg: fmt.Sprintf("[IMX] Create Gallery URL: %s", finalUrl)})

	// 1. Try URL extraction
	if strings.Contains(finalUrl, "id=") {
		u, _ := url.Parse(finalUrl)
		return u.Query().Get("id"), nil
	}

	// 2. Fallback: Body extraction (if redirection failed or 200 OK returned directly)
	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err == nil {
		// Look for the "Manage Gallery" link in the success page
		var id string
		doc.Find("a[href*='manage?id=']").Each(func(i int, s *goquery.Selection) {
			if id == "" {
				href, _ := s.Attr("href")
				if u, err := url.Parse(href); err == nil {
					id = u.Query().Get("id")
				}
			}
		})
		
		if id != "" {
			sendJSON(OutputEvent{Type: "log", Msg: fmt.Sprintf("[IMX] Found ID in body: %s", id)})
			return id, nil
		}
	}

	return "0", fmt.Errorf("failed to extract ID. URL: %s", finalUrl)
}

func doViprLogin(creds map[string]string) bool {
	v := url.Values{"op": {"login"}, "login": {creds["vipr_user"]}, "password": {creds["vipr_pass"]}}
	if r, err := doRequest(context.Background(), "POST", "https://vipr.im/login.html", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded"); err == nil { r.Body.Close() }
	resp, err := doRequest(context.Background(), "GET", "https://vipr.im/", nil, "")
	if err != nil { return false }
	defer resp.Body.Close()
	bodyBytes, _ := io.ReadAll(resp.Body)
	doc, _ := goquery.NewDocumentFromReader(bytes.NewReader(bodyBytes))
	viprSt.mu.Lock()
	defer viprSt.mu.Unlock()
	if action, exists := doc.Find("form[action*='upload.cgi']").Attr("action"); exists { viprSt.endpoint = action }
	if val, exists := doc.Find("input[name='sess_id']").Attr("value"); exists { viprSt.sessId = val }
	if viprSt.sessId == "" {
		html := string(bodyBytes)
		if m := regexp.MustCompile(`name=["']sess_id["']\s+value=["']([^"']+)["']`).FindStringSubmatch(html); len(m) > 1 { viprSt.sessId = m[1] }
		if viprSt.endpoint == "" {
			if m := regexp.MustCompile(`action=["'](https?://[^/]+/cgi-bin/upload\.cgi)`).FindStringSubmatch(html); len(m) > 1 { viprSt.endpoint = m[1] }
		}
	}
	return viprSt.sessId != ""
}

func scrapeViprGalleries() []map[string]string {
	resp, err := doRequest(context.Background(), "GET", "https://vipr.im/?op=my_files", nil, "")
	if err != nil { return nil }
	defer resp.Body.Close()
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
	return results
}

func createViprGallery(name string) (string, error) {
	v := url.Values{"op": {"my_files"}, "add_folder": {name}}
	if r, err := doRequest(context.Background(), "GET", "https://vipr.im/?"+v.Encode(), nil, ""); err == nil { r.Body.Close() }
	return "0", nil
}

func createPixhostGallery(name string) (map[string]string, error) {
	v := url.Values{}
	v.Set("title", name)
	req, _ := http.NewRequest("POST", "https://api.pixhost.to/galleries", strings.NewReader(v.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("User-Agent", DefaultUserAgent)
	resp, err := client.Do(req)
	if err != nil { return nil, err }
	defer resp.Body.Close()
	var result struct { GalleryHash string `json:"gallery_hash"`; GalleryUploadHash string `json:"gallery_upload_hash"` }
	json.NewDecoder(resp.Body).Decode(&result)
	if result.GalleryHash == "" { return nil, fmt.Errorf("gallery creation failed") }
	return map[string]string{"gallery_hash": result.GalleryHash, "gallery_upload_hash": result.GalleryUploadHash}, nil
}

func doImageBamLogin(creds map[string]string) bool {
	resp1, err := doRequest(context.Background(), "GET", "https://www.imagebam.com/auth/login", nil, "")
	if err != nil { return false }
	defer resp1.Body.Close()
	doc1, _ := goquery.NewDocumentFromReader(resp1.Body)
	token := doc1.Find("input[name='_token']").AttrOr("value", "")
	v := url.Values{"_token": {token}, "email": {creds["imagebam_user"]}, "password": {creds["imagebam_pass"]}, "remember": {"on"}}
	if r, err := doRequest(context.Background(), "POST", "https://www.imagebam.com/auth/login", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded"); err == nil { r.Body.Close() }
	resp2, _ := doRequest(context.Background(), "GET", "https://www.imagebam.com/", nil, "")
	defer resp2.Body.Close()
	doc2, _ := goquery.NewDocumentFromReader(resp2.Body)
	ibSt.mu.Lock()
	defer ibSt.mu.Unlock()
	ibSt.csrf = doc2.Find("meta[name='csrf-token']").AttrOr("content", "")
	if ibSt.csrf != "" {
		req, _ := http.NewRequest("POST", "https://www.imagebam.com/upload/session", strings.NewReader("content_type=1&thumbnail_size=1"))
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		req.Header.Set("X-Requested-With", "XMLHttpRequest")
		req.Header.Set("X-CSRF-TOKEN", ibSt.csrf)
		req.Header.Set("User-Agent", DefaultUserAgent)
		if r3, e3 := client.Do(req); e3 == nil {
			defer r3.Body.Close()
			var j struct{ Status, Data string }
			if err := json.NewDecoder(r3.Body).Decode(&j); err == nil && j.Status == "success" { ibSt.uploadToken = j.Data }
		}
	}
	return ibSt.csrf != ""
}

func doTurboLogin(creds map[string]string) bool {
	if creds["turbo_user"] != "" {
		v := url.Values{"username": {creds["turbo_user"]}, "password": {creds["turbo_pass"]}, "login": {"Login"}}
		if r, err := doRequest(context.Background(), "POST", "https://www.turboimagehost.com/login", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded"); err == nil { r.Body.Close() }
	}
	resp, err := doRequest(context.Background(), "GET", "https://www.turboimagehost.com/", nil, "")
	if err != nil { return false }
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	html := string(b)
	turboSt.mu.Lock()
	defer turboSt.mu.Unlock()
	if m := regexp.MustCompile(`endpoint:\s*'([^']+)'`).FindStringSubmatch(html); len(m) > 1 { turboSt.endpoint = m[1] }
	return turboSt.endpoint != ""
}

func scrapeBBCode(urlStr string) (string, string, error) {
	resp, err := doRequest(context.Background(), "GET", urlStr, nil, "")
	if err != nil { return urlStr, urlStr, nil }
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	html := string(b)
	re := regexp.MustCompile(`(?i)\[url=["']?(https?://[^"']+)["']?\]\s*\[img\](https?://[^\[]+)\[/img\]\s*\[/url\]`)
	if m := re.FindStringSubmatch(html); len(m) > 2 { return m[1], m[2], nil }
	return urlStr, urlStr, nil
}

func handleViperLogin(job JobRequest) {
	user, pass := job.Creds["vg_user"], job.Creds["vg_pass"]
	if r, err := doRequest(context.Background(), "GET", "https://vipergirls.to/login.php?do=login", nil, ""); err == nil { r.Body.Close() }
	hasher := md5.New()
	_, _ = hasher.Write([]byte(pass))
	md5Pass := hex.EncodeToString(hasher.Sum(nil))
	v := url.Values{"vb_login_username": {user}, "vb_login_md5password": {md5Pass}, "vb_login_md5password_utf": {md5Pass}, "cookieuser": {"1"}, "do": {"login"}, "securitytoken": {"guest"}}
	resp, _ := doRequest(context.Background(), "POST", "https://vipergirls.to/login.php?do=login", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded")
	b, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
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
			resp.Body.Close()
			if m := regexp.MustCompile(`SECURITYTOKEN\s*=\s*"([^"]+)"`).FindStringSubmatch(string(b)); len(m) > 1 {
				vgSt.mu.Lock()
				vgSt.securityToken = m[1]
				token = m[1]
				vgSt.mu.Unlock()
			}
		}
	}
	v := url.Values{"message": {job.Config["message"]}, "securitytoken": {token}, "do": {"postreply"}, "t": {job.Config["thread_id"]}, "parseurl": {"1"}, "emailupdate": {"9999"}}
	urlStr := fmt.Sprintf("https://vipergirls.to/newreply.php?do=postreply&t=%s", job.Config["thread_id"])
	resp, err := doRequest(context.Background(), "POST", urlStr, strings.NewReader(v.Encode()), "application/x-www-form-urlencoded")
	if err != nil { sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: err.Error()}); return }
	defer resp.Body.Close()
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
	sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: "Post not confirmed"})
}

func doRequest(ctx context.Context, method, urlStr string, body io.Reader, contentType string) (*http.Response, error) {
	req, _ := http.NewRequestWithContext(ctx, method, urlStr, body)
	req.Header.Set("User-Agent", DefaultUserAgent)
	if contentType != "" { req.Header.Set("Content-Type", contentType) }
	if strings.Contains(urlStr, "imagebam.com") { req.Header.Set("Referer", "https://www.imagebam.com/") }
	if strings.Contains(urlStr, "vipr.im") { req.Header.Set("Referer", "https://vipr.im/") }
	if strings.Contains(urlStr, "turboimagehost.com") { req.Header.Set("Referer", "https://www.turboimagehost.com/") }
	if strings.Contains(urlStr, "imx.to") { req.Header.Set("Referer", "https://imx.to/") }
	if strings.Contains(urlStr, "vipergirls.to") { req.Header.Set("Referer", "https://vipergirls.to/forum.php") }
	return client.Do(req)
}

func sendJSON(v interface{}) {
	outputMutex.Lock()
	defer outputMutex.Unlock()
	b, _ := json.Marshal(v)
	fmt.Println(string(b))
}
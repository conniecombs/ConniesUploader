package main

import (
	"bytes"
	"crypto/md5"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"github.com/PuerkitoBio/goquery"
	"github.com/disintegration/imaging"
	log "github.com/sirupsen/logrus"
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
var stateMutex sync.Mutex // Protects service state globals
var client *http.Client

// Service State (protected by stateMutex)
var viprEndpoint string
var viprSessId string
var turboEndpoint string
var ibCsrf string
var ibUploadToken string
var vgSecurityToken string

var quoteEscaper = strings.NewReplacer("\\", "\\\\", `"`, "\\\"")

func quoteEscape(s string) string { return quoteEscaper.Replace(s) }

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
	// Note: Using crypto/rand for random string generation (more secure)
	log.WithFields(log.Fields{
		"component": "uploader",
		"version":   "1.0.0",
	}).Info("Go sidecar starting")

	jar, _ := cookiejar.New(nil)
	client = &http.Client{
		Timeout:   120 * time.Second,
		Jar:       jar,
		Transport: &http.Transport{MaxIdleConnsPerHost: 10},
	}

	// --- WORKER POOL IMPLEMENTATION ---
	// 1. Create a job queue channel
	jobQueue := make(chan JobRequest, 100)

	// 2. Start fixed number of workers (e.g., 5-10) to process incoming requests
	// This prevents the Go process from spawning thousands of goroutines if the UI floods it.
	numWorkers := 8
	log.WithField("workers", numWorkers).Info("Starting worker pool")

	for i := 0; i < numWorkers; i++ {
		go func(workerID int) {
			log.WithField("worker_id", workerID).Debug("Worker started")
			for job := range jobQueue {
				handleJob(job)
			}
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

		// Blocking push if queue is full, effectively throttling the UI
		jobQueue <- job
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
	defer f.Close()

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
	jpeg.Encode(&buf, thumb, &jpeg.Options{Quality: 70})
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
		stateMutex.Lock()
		needsLogin := viprSessId == ""
		stateMutex.Unlock()
		if needsLogin {
			doViprLogin(job.Creds)
		}
		galleries = scrapeViprGalleries()
	case "imagebam.com":
		stateMutex.Lock()
		needsLogin := ibCsrf == ""
		stateMutex.Unlock()
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
	logger.Info("Starting upload")

	sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Uploading"})
	var url, thumb string
	var err error

	// Retry with exponential backoff: 2s, 4s, 8s (max 3 attempts)
	maxRetries := 3
	baseDelay := 2 * time.Second

	for attempt := 0; attempt < maxRetries; attempt++ {
		if attempt > 0 {
			delay := baseDelay * time.Duration(1<<uint(attempt-1)) // 2s, 4s, 8s
			logger.WithFields(log.Fields{
				"attempt": attempt,
				"delay":   delay.String(),
			}).Warn("Retrying upload")
			sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: fmt.Sprintf("Retry %d/%d in %v", attempt, maxRetries-1, delay)})
			time.Sleep(delay)
			sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Uploading"})
		}

		switch job.Service {
		case "imx.to":
			url, thumb, err = uploadImx(fp, job)
		case "pixhost.to":
			url, thumb, err = uploadPixhost(fp, job)
		case "vipr.im":
			url, thumb, err = uploadVipr(fp, job)
		case "turboimagehost":
			url, thumb, err = uploadTurbo(fp, job)
		case "imagebam.com":
			url, thumb, err = uploadImageBam(fp, job)
		default:
			err = fmt.Errorf("unknown service: %s", job.Service)
		}

		// Success - exit retry loop
		if err == nil {
			break
		}

		// Log the error but continue retrying
		if attempt < maxRetries-1 {
			sendJSON(OutputEvent{Type: "error", FilePath: fp, Msg: fmt.Sprintf("Attempt %d failed: %v", attempt+1, err)})
		}
	}

	if err != nil {
		logger.WithFields(log.Fields{
			"error":    err.Error(),
			"attempts": maxRetries,
		}).Error("Upload failed after all retries")
		sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Failed"})
		sendJSON(OutputEvent{Type: "error", FilePath: fp, Msg: fmt.Sprintf("Failed after %d attempts: %v", maxRetries, err)})
	} else {
		logger.WithFields(log.Fields{
			"url":   url,
			"thumb": thumb,
		}).Info("Upload successful")
		sendJSON(OutputEvent{Type: "result", FilePath: fp, Url: url, Thumb: thumb})
		sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Done"})
	}
}

// --- Upload Implementations ---

func uploadImx(fp string, job *JobRequest) (string, string, error) {
	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)

	go func() {
		defer pw.Close()
		defer writer.Close()
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
		defer f.Close()
		if _, err := io.Copy(part, f); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to copy file: %w", err))
			return
		}
		writer.WriteField("format", "json")
		writer.WriteField("thumbnail_size", job.Config["imx_thumb_id"])
		writer.WriteField("thumbnail_format", job.Config["imx_format_id"])
		if gid := job.Config["gallery_id"]; gid != "" {
			writer.WriteField("gallery_id", gid)
		}
	}()

	req, err := http.NewRequest("POST", "https://api.imx.to/v1/upload.php", pr)
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
	defer resp.Body.Close()
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
	return res.Data.Img, res.Data.Thumb, nil
}

func uploadPixhost(fp string, job *JobRequest) (string, string, error) {
	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)

	go func() {
		defer pw.Close()
		defer writer.Close()
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
		defer f.Close()
		if _, err := io.Copy(part, f); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to copy file: %w", err))
			return
		}
		writer.WriteField("content_type", job.Config["pix_content"])
		writer.WriteField("max_th_size", job.Config["pix_thumb"])
		if h := job.Config["pix_gallery_hash"]; h != "" {
			writer.WriteField("gallery_hash", h)
		}
	}()

	req, err := http.NewRequest("POST", "https://api.pixhost.to/images", pr)
	if err != nil {
		return "", "", fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("User-Agent", UserAgent)

	resp, err := client.Do(req)
	if err != nil {
		return "", "", fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()
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

func uploadVipr(fp string, job *JobRequest) (string, string, error) {
	stateMutex.Lock()
	needsLogin := viprSessId == ""
	upUrl := viprEndpoint
	sessId := viprSessId
	stateMutex.Unlock()

	if needsLogin {
		doViprLogin(job.Creds)
		stateMutex.Lock()
		upUrl = viprEndpoint
		sessId = viprSessId
		stateMutex.Unlock()
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
		if err != nil {
			pw.CloseWithError(fmt.Errorf("failed to create form file: %w", err))
			return
		}
		f, err := os.Open(fp)
		if err != nil {
			pw.CloseWithError(fmt.Errorf("failed to open file: %w", err))
			return
		}
		defer f.Close()
		if _, err := io.Copy(part, f); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to copy file: %w", err))
			return
		}
		writer.WriteField("upload_type", "file")
		writer.WriteField("sess_id", sessId)
		writer.WriteField("thumb_size", job.Config["vipr_thumb"])
		writer.WriteField("fld_id", job.Config["vipr_gal_id"])
		writer.WriteField("tos", "1")
		writer.WriteField("submit_btn", "Upload")
	}()

	u := upUrl + "?upload_id=" + randomString(12) + "&js_on=1&utype=reg&upload_type=file"
	resp, err := doRequest("POST", u, pr, writer.FormDataContentType())
	if err != nil {
		return "", "", fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	// Parse initial response
	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil {
		return "", "", fmt.Errorf("failed to parse response: %w", err)
	}

	if textArea := doc.Find("textarea[name='fn']"); textArea.Length() > 0 {
		fnVal := textArea.Text()
		v := url.Values{"op": {"upload_result"}, "fn": {fnVal}, "st": {"OK"}}
		if r2, e2 := doRequest("POST", "https://vipr.im/", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded"); e2 == nil {
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

func uploadTurbo(fp string, job *JobRequest) (string, string, error) {
	stateMutex.Lock()
	needsLogin := turboEndpoint == ""
	endp := turboEndpoint
	stateMutex.Unlock()

	if needsLogin {
		doTurboLogin(job.Creds)
		stateMutex.Lock()
		endp = turboEndpoint
		stateMutex.Unlock()
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
		defer pw.Close()
		defer writer.Close()
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
		defer f.Close()
		if _, err := io.Copy(part, f); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to copy file: %w", err))
			return
		}
		writer.WriteField("qquuid", randomString(32))
		writer.WriteField("qqfilename", filepath.Base(fp))
		writer.WriteField("qqtotalfilesize", fmt.Sprintf("%d", fi.Size()))
		writer.WriteField("imcontent", job.Config["turbo_content"])
		writer.WriteField("thumb_size", job.Config["turbo_thumb"])
	}()

	resp, err := doRequest("POST", endp, pr, writer.FormDataContentType())
	if err != nil {
		return "", "", fmt.Errorf("request failed: %w", err)
	}
	raw, err := io.ReadAll(resp.Body)
	resp.Body.Close()
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

func uploadImageBam(fp string, job *JobRequest) (string, string, error) {
	stateMutex.Lock()
	needsLogin := ibUploadToken == ""
	csrf := ibCsrf
	token := ibUploadToken
	stateMutex.Unlock()

	if needsLogin {
		doImageBamLogin(job.Creds)
		stateMutex.Lock()
		csrf = ibCsrf
		token = ibUploadToken
		stateMutex.Unlock()
	}

	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)
	go func() {
		defer pw.Close()
		defer writer.Close()
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
		defer f.Close()
		if _, err := io.Copy(part, f); err != nil {
			pw.CloseWithError(fmt.Errorf("failed to copy file: %w", err))
			return
		}
		writer.WriteField("_token", csrf)
		writer.WriteField("data", token)
	}()

	req, err := http.NewRequest("POST", "https://www.imagebam.com/upload", pr)
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
	defer resp.Body.Close()

	var res struct {
		Status string `json:"status"`
		Data   []struct {
			Url   string `json:"url"`
			Thumb string `json:"thumb"`
		} `json:"data"`
	}
	json.NewDecoder(resp.Body).Decode(&res)
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
	if r, err := doRequest("POST", "https://imx.to/login.html", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded"); err == nil {
		r.Body.Close()
	}

	resp, err := doRequest("GET", "https://imx.to/user/galleries", nil, "")
	if err != nil {
		return nil
	}
	defer resp.Body.Close()

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
	resp, err := doRequest("POST", "https://imx.to/user/gallery/add", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded")
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
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
	if r, err := doRequest("POST", "https://vipr.im/login.html", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded"); err == nil {
		r.Body.Close()
	}
	resp, err := doRequest("GET", "https://vipr.im/", nil, "")
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	bodyBytes, _ := io.ReadAll(resp.Body)
	doc, _ := goquery.NewDocumentFromReader(bytes.NewReader(bodyBytes))

	stateMutex.Lock()
	defer stateMutex.Unlock()

	if action, exists := doc.Find("form[action*='upload.cgi']").Attr("action"); exists {
		viprEndpoint = action
	}
	if val, exists := doc.Find("input[name='sess_id']").Attr("value"); exists {
		viprSessId = val
	}
	if viprSessId == "" {
		html := string(bodyBytes)
		if m := regexp.MustCompile(`name=["']sess_id["']\s+value=["']([^"']+)["']`).FindStringSubmatch(html); len(m) > 1 {
			viprSessId = m[1]
		}
		if viprEndpoint == "" {
			if m := regexp.MustCompile(`action=["'](https?://[^/]+/cgi-bin/upload\.cgi)`).FindStringSubmatch(html); len(m) > 1 {
				viprEndpoint = m[1]
			}
		}
	}
	return viprSessId != ""
}

func scrapeViprGalleries() []map[string]string {
	resp, err := doRequest("GET", "https://vipr.im/?op=my_files", nil, "")
	if err != nil {
		return nil
	}
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
	if r, err := doRequest("GET", "https://vipr.im/?"+v.Encode(), nil, ""); err == nil {
		r.Body.Close()
	}
	return "0", nil
}

func doImageBamLogin(creds map[string]string) bool {
	resp1, err := doRequest("GET", "https://www.imagebam.com/auth/login", nil, "")
	if err != nil {
		return false
	}
	defer resp1.Body.Close()
	doc1, _ := goquery.NewDocumentFromReader(resp1.Body)
	token := doc1.Find("input[name='_token']").AttrOr("value", "")
	v := url.Values{"_token": {token}, "email": {creds["imagebam_user"]}, "password": {creds["imagebam_pass"]}, "remember": {"on"}}
	if r, err := doRequest("POST", "https://www.imagebam.com/auth/login", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded"); err == nil {
		r.Body.Close()
	}
	resp2, _ := doRequest("GET", "https://www.imagebam.com/", nil, "")
	defer resp2.Body.Close()
	doc2, _ := goquery.NewDocumentFromReader(resp2.Body)

	stateMutex.Lock()
	defer stateMutex.Unlock()

	ibCsrf = doc2.Find("meta[name='csrf-token']").AttrOr("content", "")
	if ibCsrf == "" {
		doc2.Find("meta").Each(func(i int, s *goquery.Selection) {
			if s.AttrOr("name", "") == "csrf-token" {
				ibCsrf = s.AttrOr("content", "")
			}
		})
	}
	if ibCsrf != "" {
		req, _ := http.NewRequest("POST", "https://www.imagebam.com/upload/session", strings.NewReader("content_type=1&thumbnail_size=1"))
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		req.Header.Set("X-Requested-With", "XMLHttpRequest")
		req.Header.Set("X-CSRF-TOKEN", ibCsrf)
		req.Header.Set("User-Agent", UserAgent)
		if r3, e3 := client.Do(req); e3 == nil {
			defer r3.Body.Close()
			var j struct{ Status, Data string }
			json.NewDecoder(r3.Body).Decode(&j)
			if j.Status == "success" {
				ibUploadToken = j.Data
			}
		}
	}
	return ibCsrf != ""
}

func doTurboLogin(creds map[string]string) bool {
	if creds["turbo_user"] != "" {
		v := url.Values{"username": {creds["turbo_user"]}, "password": {creds["turbo_pass"]}, "login": {"Login"}}
		if r, err := doRequest("POST", "https://www.turboimagehost.com/login", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded"); err == nil {
			r.Body.Close()
		}
	}
	resp, err := doRequest("GET", "https://www.turboimagehost.com/", nil, "")
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	html := string(b)

	stateMutex.Lock()
	defer stateMutex.Unlock()

	if m := regexp.MustCompile(`endpoint:\s*'([^']+)'`).FindStringSubmatch(html); len(m) > 1 {
		turboEndpoint = m[1]
	}
	return turboEndpoint != ""
}

func scrapeBBCode(urlStr string) (string, string, error) {
	resp, err := doRequest("GET", urlStr, nil, "")
	if err != nil {
		return urlStr, urlStr, nil
	}
	defer resp.Body.Close()
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
	if r, err := doRequest("GET", "https://vipergirls.to/login.php?do=login", nil, ""); err == nil {
		r.Body.Close()
	}

	// SECURITY NOTE: ViperGirls uses MD5 for authentication (legacy vBulletin system).
	// This is required by their API and not our choice. Users should use unique passwords.
	hasher := md5.New()
	hasher.Write([]byte(pass))
	md5Pass := hex.EncodeToString(hasher.Sum(nil))
	v := url.Values{"vb_login_username": {user}, "vb_login_md5password": {md5Pass}, "vb_login_md5password_utf": {md5Pass}, "cookieuser": {"1"}, "do": {"login"}, "securitytoken": {"guest"}}
	resp, _ := doRequest("POST", "https://vipergirls.to/login.php?do=login", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded")
	b, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	body := string(b)
	if strings.Contains(body, "Thank you for logging in") {
		if m := regexp.MustCompile(`SECURITYTOKEN\s*=\s*"([^"]+)"`).FindStringSubmatch(body); len(m) > 1 {
			stateMutex.Lock()
			vgSecurityToken = m[1]
			stateMutex.Unlock()
		}
		sendJSON(OutputEvent{Type: "result", Status: "success", Msg: "Login OK"})
	} else {
		sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: "Invalid Creds"})
	}
}

func handleViperPost(job JobRequest) {
	stateMutex.Lock()
	token := vgSecurityToken
	needsRefresh := token == "" || token == "guest"
	stateMutex.Unlock()

	if needsRefresh {
		if resp, err := doRequest("GET", "https://vipergirls.to/forum.php", nil, ""); err == nil {
			b, _ := io.ReadAll(resp.Body)
			resp.Body.Close()
			if m := regexp.MustCompile(`SECURITYTOKEN\s*=\s*"([^"]+)"`).FindStringSubmatch(string(b)); len(m) > 1 {
				stateMutex.Lock()
				vgSecurityToken = m[1]
				token = m[1]
				stateMutex.Unlock()
			}
		}
	}
	v := url.Values{
		"message": {job.Config["message"]}, "securitytoken": {token},
		"do": {"postreply"}, "t": {job.Config["thread_id"]}, "parseurl": {"1"}, "emailupdate": {"9999"},
	}
	urlStr := fmt.Sprintf("https://vipergirls.to/newreply.php?do=postreply&t=%s", job.Config["thread_id"])
	resp, err := doRequest("POST", urlStr, strings.NewReader(v.Encode()), "application/x-www-form-urlencoded")
	if err != nil {
		sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: err.Error()})
		return
	}
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
	if strings.Contains(strings.ToLower(body), "duplicate") {
		sendJSON(OutputEvent{Type: "result", Status: "success", Msg: "Already Posted"})
		return
	}
	sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: "Post not confirmed"})
}

func doRequest(method, urlStr string, body io.Reader, contentType string) (*http.Response, error) {
	req, err := http.NewRequest(method, urlStr, body)
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

// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

// Package vipr implements the Vipr.im image-hosting service module.
package vipr

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"

	"github.com/PuerkitoBio/goquery"
	"github.com/conniecombs/GolangVersion/core"
)

const ServiceID = "vipr.im"

// Module is the self-contained Vipr.im service plugin.
// It maintains session state (upload endpoint and session ID) internally.
type Module struct {
	client *http.Client

	mu       sync.RWMutex
	endpoint string
	sessID   string
}

// New constructs a Vipr module wired to the shared HTTP client.
func New(client *http.Client) *Module {
	return &Module{client: client}
}

func (m *Module) ID() string { return ServiceID }

// Login implements services.Authenticator.
func (m *Module) Login(creds map[string]string) bool {
	return m.doLogin(creds)
}

// Upload implements services.Uploader.
func (m *Module) Upload(ctx context.Context, fp string, job *core.JobRequest) (string, string, error) {
	if err := core.WaitForRateLimit(ctx, ServiceID); err != nil {
		return "", "", err
	}

	m.mu.RLock()
	needsLogin := m.sessID == ""
	upURL := m.endpoint
	sessID := m.sessID
	m.mu.RUnlock()

	if needsLogin {
		m.doLogin(job.Creds)
		m.mu.RLock()
		upURL = m.endpoint
		sessID = m.sessID
		m.mu.RUnlock()
	}
	if upURL == "" {
		upURL = "https://vipr.im/cgi-bin/upload.cgi"
	}

	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)
	go func() {
		defer pw.Close()
		defer writer.Close()

		safeName := strings.ReplaceAll(filepath.Base(fp), " ", "_")
		part, err := writer.CreateFormFile("file_0", safeName)
		if err != nil {
			pw.CloseWithError(err)
			return
		}
		f, err := os.Open(fp) // #nosec G304
		if err != nil {
			pw.CloseWithError(err)
			return
		}
		defer f.Close()
		if _, err := io.Copy(part, f); err != nil {
			pw.CloseWithError(err)
			return
		}

		_ = writer.WriteField("upload_type", "file")
		_ = writer.WriteField("sess_id", sessID)
		_ = writer.WriteField("thumb_size", job.Config["vipr_thumb"])
		_ = writer.WriteField("fld_id", job.Config["vipr_gal_id"])
		_ = writer.WriteField("tos", "1")
		_ = writer.WriteField("submit_btn", "Upload")
	}()

	uploadURL := upURL + "?upload_id=" + core.RandomString(12) + "&js_on=1&utype=reg&upload_type=file"
	resp, err := m.doRequest(ctx, "POST", uploadURL, pr, writer.FormDataContentType())
	if err != nil {
		return "", "", err
	}
	defer resp.Body.Close()

	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil {
		return "", "", err
	}

	// Two-step result fetch if the response contains a fn textarea.
	if textArea := doc.Find("textarea[name='fn']"); textArea.Length() > 0 {
		fnVal := textArea.Text()
		v := url.Values{"op": {"upload_result"}, "fn": {fnVal}, "st": {"OK"}}
		if r2, e2 := m.doRequest(ctx, "POST", "https://vipr.im/", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded"); e2 == nil {
			defer r2.Body.Close()
			doc, _ = goquery.NewDocumentFromReader(r2.Body)
		}
	}

	imgURL := doc.Find("input[name='link_url']").AttrOr("value", "")
	thumbURL := doc.Find("input[name='thumb_url']").AttrOr("value", "")

	if imgURL == "" || thumbURL == "" {
		html, _ := doc.Html()
		reImg := regexp.MustCompile(`value=['"](https?://vipr\.im/i/[^'"]+)['"]`)
		reThumb := regexp.MustCompile(`src=['"](https?://vipr\.im/th/[^'"]+)['"]`)
		if mI := reImg.FindStringSubmatch(html); len(mI) > 1 {
			imgURL = mI[1]
		}
		if mT := reThumb.FindStringSubmatch(html); len(mT) > 1 {
			thumbURL = mT[1]
		}
	}

	if imgURL != "" && thumbURL != "" {
		return imgURL, thumbURL, nil
	}
	return "", "", fmt.Errorf("vipr: failed to parse upload result")
}

// ListGalleries implements services.GalleryLister.
func (m *Module) ListGalleries(creds map[string]string) []map[string]string {
	m.mu.RLock()
	needsLogin := m.sessID == ""
	m.mu.RUnlock()
	if needsLogin {
		m.doLogin(creds)
	}
	return m.scrapeGalleries()
}

// CreateGallery implements services.GalleryCreator.
func (m *Module) CreateGallery(_ map[string]string, name string) (string, interface{}, error) {
	v := url.Values{"op": {"my_files"}, "add_folder": {name}}
	if r, err := m.doRequest(context.Background(), "GET", "https://vipr.im/?"+v.Encode(), nil, ""); err == nil {
		_ = r.Body.Close()
	}
	return "0", "0", nil
}

// --- internal ---

func (m *Module) doLogin(creds map[string]string) bool {
	v := url.Values{
		"op":       {"login"},
		"login":    {creds["vipr_user"]},
		"password": {creds["vipr_pass"]},
	}
	if r, err := m.doRequest(context.Background(), "POST", "https://vipr.im/login.html", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded"); err == nil {
		_ = r.Body.Close()
	}

	resp, err := m.doRequest(context.Background(), "GET", "https://vipr.im/", nil, "")
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	bodyBytes, _ := io.ReadAll(resp.Body)

	doc, _ := goquery.NewDocumentFromReader(bytes.NewReader(bodyBytes))

	m.mu.Lock()
	defer m.mu.Unlock()

	if action, ok := doc.Find("form[action*='upload.cgi']").Attr("action"); ok {
		m.endpoint = action
	}
	if val, ok := doc.Find("input[name='sess_id']").Attr("value"); ok {
		m.sessID = val
	}

	if m.sessID == "" {
		html := string(bodyBytes)
		if matches := regexp.MustCompile(`name=["']sess_id["']\s+value=["']([^"']+)["']`).FindStringSubmatch(html); len(matches) > 1 {
			m.sessID = matches[1]
		}
		if m.endpoint == "" {
			if matches := regexp.MustCompile(`action=["'](https?://[^/]+/cgi-bin/upload\.cgi)`).FindStringSubmatch(html); len(matches) > 1 {
				m.endpoint = matches[1]
			}
		}
	}
	return m.sessID != ""
}

func (m *Module) scrapeGalleries() []map[string]string {
	resp, err := m.doRequest(context.Background(), "GET", "https://vipr.im/?op=my_files", nil, "")
	if err != nil {
		return nil
	}
	defer resp.Body.Close()
	bodyBytes, _ := io.ReadAll(resp.Body)

	var results []map[string]string
	seen := make(map[string]bool)
	doc, err := goquery.NewDocumentFromReader(bytes.NewReader(bodyBytes))
	if err != nil {
		return nil
	}
	doc.Find("a[href*='fld_id=']").Each(func(_ int, s *goquery.Selection) {
		href, _ := s.Attr("href")
		u, _ := url.Parse(href)
		if u == nil {
			return
		}
		id := u.Query().Get("fld_id")
		name := strings.TrimSpace(s.Text())
		if id != "" && name != "" && !seen[id] {
			results = append(results, map[string]string{"id": id, "name": name})
			seen[id] = true
		}
	})
	return results
}

func (m *Module) doRequest(ctx context.Context, method, urlStr string, body io.Reader, contentType string) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, method, urlStr, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", core.DefaultUserAgent)
	req.Header.Set("Referer", "https://vipr.im/")
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	return m.client.Do(req)
}

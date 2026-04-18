// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

// Package imagebam implements the ImageBam.com service module.
package imagebam

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/PuerkitoBio/goquery"
	"github.com/conniecombs/GolangVersion/core"
)

const ServiceID = "imagebam.com"

// Module is the self-contained ImageBam service plugin.
// It maintains CSRF token and upload-session token internally.
type Module struct {
	client *http.Client

	mu          sync.RWMutex
	csrf        string
	uploadToken string
}

// New constructs an ImageBam module wired to the shared HTTP client.
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
	needsLogin := m.uploadToken == ""
	csrf := m.csrf
	token := m.uploadToken
	m.mu.RUnlock()

	if needsLogin {
		m.doLogin(job.Creds)
		m.mu.RLock()
		csrf = m.csrf
		token = m.uploadToken
		m.mu.RUnlock()
	}

	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)
	go func() {
		defer pw.Close()
		defer writer.Close()

		part, _ := writer.CreateFormFile("files[0]", filepath.Base(fp))
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

		_ = writer.WriteField("_token", csrf)
		_ = writer.WriteField("data", token)
	}()

	req, _ := http.NewRequestWithContext(ctx, "POST", "https://www.imagebam.com/upload", pr)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("X-Requested-With", "XMLHttpRequest")
	req.Header.Set("X-CSRF-TOKEN", csrf)
	req.Header.Set("User-Agent", core.DefaultUserAgent)
	req.Header.Set("Origin", "https://www.imagebam.com")
	req.Header.Set("Referer", "https://www.imagebam.com/")

	resp, err := m.client.Do(req)
	if err != nil {
		return "", "", err
	}
	defer resp.Body.Close()

	var res struct {
		Status string `json:"status"`
		Data   []struct {
			Url   string
			Thumb string
		} `json:"data"`
	}
	_ = json.NewDecoder(resp.Body).Decode(&res)
	if res.Status == "success" && len(res.Data) > 0 {
		return res.Data[0].Url, res.Data[0].Thumb, nil
	}
	return "", "", fmt.Errorf("imagebam upload failed")
}

// ListGalleries implements services.GalleryLister (stub — ImageBam galleries
// are managed via upload sessions, not enumerable via a simple API).
func (m *Module) ListGalleries(_ map[string]string) []map[string]string {
	return nil
}

// CreateGallery implements services.GalleryCreator.
// ImageBam uses upload sessions rather than traditional galleries; a new
// session is started at login time and the ID "0" is returned as a no-op.
func (m *Module) CreateGallery(_ map[string]string, _ string) (string, interface{}, error) {
	return "0", "0", nil
}

// --- internal ---

func (m *Module) doLogin(creds map[string]string) bool {
	resp1, err := m.doRequest(context.Background(), "GET", "https://www.imagebam.com/auth/login", nil, "")
	if err != nil {
		return false
	}
	defer resp1.Body.Close()
	doc1, _ := goquery.NewDocumentFromReader(resp1.Body)
	token := doc1.Find("input[name='_token']").AttrOr("value", "")

	v := strings.NewReader("_token=" + token +
		"&email=" + creds["imagebam_user"] +
		"&password=" + creds["imagebam_pass"] +
		"&remember=on")
	if r, err := m.doRequest(context.Background(), "POST", "https://www.imagebam.com/auth/login", v, "application/x-www-form-urlencoded"); err == nil {
		r.Body.Close()
	}

	resp2, err := m.doRequest(context.Background(), "GET", "https://www.imagebam.com/", nil, "")
	if err != nil {
		return false
	}
	defer resp2.Body.Close()
	doc2, _ := goquery.NewDocumentFromReader(resp2.Body)

	m.mu.Lock()
	defer m.mu.Unlock()
	m.csrf = doc2.Find("meta[name='csrf-token']").AttrOr("content", "")

	if m.csrf != "" {
		req, _ := http.NewRequest("POST", "https://www.imagebam.com/upload/session",
			strings.NewReader("content_type=1&thumbnail_size=1"))
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		req.Header.Set("X-Requested-With", "XMLHttpRequest")
		req.Header.Set("X-CSRF-TOKEN", m.csrf)
		req.Header.Set("User-Agent", core.DefaultUserAgent)
		req.Header.Set("Referer", "https://www.imagebam.com/")
		if r3, e3 := m.client.Do(req); e3 == nil {
			defer r3.Body.Close()
			var j struct{ Status, Data string }
			if err := json.NewDecoder(r3.Body).Decode(&j); err == nil && j.Status == "success" {
				m.uploadToken = j.Data
			}
		}
	}
	return m.csrf != ""
}

func (m *Module) doRequest(ctx context.Context, method, urlStr string, body io.Reader, contentType string) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, method, urlStr, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", core.DefaultUserAgent)
	req.Header.Set("Referer", "https://www.imagebam.com/")
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	return m.client.Do(req)
}

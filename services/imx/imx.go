// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

// Package imx implements the IMX.to image-hosting service module.
package imx

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/PuerkitoBio/goquery"
	"github.com/conniecombs/GolangVersion/core"
)

const ServiceID = "imx.to"

// Module is the self-contained IMX.to service plugin.
// It owns its own HTTP client reference and session state, making it
// completely independent of every other service module.
type Module struct {
	client *http.Client

	mu         sync.RWMutex
	isLoggedIn bool
}

// New constructs an IMX module wired to the shared HTTP client.
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

	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)
	go func() {
		defer pw.Close()
		defer writer.Close()

		part, _ := writer.CreateFormFile("image", filepath.Base(fp))
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

		_ = writer.WriteField("format", "json")
		_ = writer.WriteField("adult", "1")
		_ = writer.WriteField("upload_type", "file")
		_ = writer.WriteField("simple_upload", "Upload")

		sid := SizeID(job.Config["imx_thumb_id"])
		_ = writer.WriteField("thumbnail_size", sid)
		_ = writer.WriteField("thumb_size_container", sid)
		_ = writer.WriteField("thumbnail_format", FormatID(job.Config["imx_format_id"]))

		if gid := job.Config["gallery_id"]; gid != "" {
			_ = writer.WriteField("gallery_id", gid)
		}
	}()

	req, _ := http.NewRequestWithContext(ctx, "POST", "https://api.imx.to/v1/upload.php", pr)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("X-API-KEY", job.Creds["api_key"])
	req.Header.Set("User-Agent", core.DefaultUserAgent)
	req.Header.Set("Referer", "https://imx.to/")

	resp, err := m.client.Do(req)
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
	_ = json.Unmarshal(raw, &res)
	if res.Status != "success" {
		return "", "", fmt.Errorf("imx upload failed")
	}
	return res.Data.Img, res.Data.Thumb, nil
}

// ListGalleries implements services.GalleryLister.
func (m *Module) ListGalleries(creds map[string]string) []map[string]string {
	m.doLogin(creds)
	resp, err := m.doRequest(context.Background(), "GET", "https://imx.to/user/galleries", nil, "")
	if err != nil {
		return nil
	}
	defer resp.Body.Close()

	doc, _ := goquery.NewDocumentFromReader(resp.Body)
	var results []map[string]string
	seen := make(map[string]bool)
	doc.Find("a").Each(func(_ int, s *goquery.Selection) {
		href, _ := s.Attr("href")
		if !strings.Contains(href, "/g/") {
			return
		}
		parts := strings.Split(href, "/g/")
		if len(parts) < 2 {
			return
		}
		id := strings.Split(strings.Split(parts[1], "?")[0], "/")[0]
		name := strings.TrimSpace(s.Find("i").Text())
		if name != "" && !seen[id] {
			results = append(results, map[string]string{"id": id, "name": name})
			seen[id] = true
		}
	})
	return results
}

// CreateGallery implements services.GalleryCreator.
func (m *Module) CreateGallery(creds map[string]string, name string) (string, interface{}, error) {
	if !m.doLogin(creds) {
		return "", nil, fmt.Errorf("IMX login failed — check credentials")
	}
	id, err := m.createGallery(name)
	if err != nil {
		return "", nil, err
	}
	return id, id, nil
}

// --- internal helpers ---

func (m *Module) doLogin(creds map[string]string) bool {
	m.mu.RLock()
	if m.isLoggedIn {
		m.mu.RUnlock()
		return true
	}
	m.mu.RUnlock()

	user := creds["imx_user"]
	pass := creds["imx_pass"]
	if user == "" || pass == "" {
		return false
	}

	loginURL := "https://imx.to/login.php"
	if r, err := m.doRequest(context.Background(), "GET", loginURL, nil, ""); err == nil {
		_ = r.Body.Close()
	} else {
		core.SendJSON(core.OutputEvent{Type: "error", Msg: fmt.Sprintf("IMX pre-login failed: %v", err)})
		return false
	}

	core.SendJSON(core.OutputEvent{Type: "log", Msg: "IMX: starting web login…"})
	v := url.Values{
		"usr_email": {user},
		"pwd":       {pass},
		"doLogin":   {"Login"},
		"remember":  {"1"},
	}
	resp, err := m.doRequest(context.Background(), "POST", loginURL, strings.NewReader(v.Encode()), "application/x-www-form-urlencoded")
	if err != nil {
		core.SendJSON(core.OutputEvent{Type: "error", Msg: fmt.Sprintf("IMX login request failed: %v", err)})
		return false
	}
	defer resp.Body.Close()

	finalURL := resp.Request.URL.String()
	core.SendJSON(core.OutputEvent{Type: "log", Msg: fmt.Sprintf("IMX login final URL: %s", finalURL)})

	bodyBytes, _ := io.ReadAll(resp.Body)
	body := string(bodyBytes)

	success := strings.Contains(finalURL, "dashboard") || strings.Contains(finalURL, "galleries") ||
		strings.Contains(strings.ToLower(body), "logout") || strings.Contains(body, "Balance")
	if strings.Contains(body, "login_form") || strings.Contains(body, "Sign Up") || strings.Contains(body, "Incorrect username") {
		success = false
	}

	if success {
		m.mu.Lock()
		m.isLoggedIn = true
		m.mu.Unlock()
		core.SendJSON(core.OutputEvent{Type: "log", Msg: "IMX login: verified success"})
		return true
	}

	snippet := body
	if len(snippet) > 500 {
		snippet = snippet[:500]
	}
	core.SendJSON(core.OutputEvent{Type: "error", Msg: fmt.Sprintf("IMX login failed. URL: %s body: %s", finalURL, snippet)})
	return false
}

func (m *Module) createGallery(name string) (string, error) {
	v := url.Values{"gallery_name": {name}, "submit_new_gallery": {"Add"}}
	req, _ := http.NewRequest("POST", "https://imx.to/user/gallery/add", strings.NewReader(v.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("User-Agent", core.DefaultUserAgent)
	req.Header.Set("Referer", "https://imx.to/user/gallery/add")

	resp, err := m.client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	finalURL := resp.Request.URL.String()
	core.SendJSON(core.OutputEvent{Type: "log", Msg: fmt.Sprintf("[IMX] create gallery URL: %s", finalURL)})

	if strings.Contains(finalURL, "id=") {
		u, _ := url.Parse(finalURL)
		return u.Query().Get("id"), nil
	}

	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err == nil {
		var id string
		doc.Find("a[href*='manage?id=']").Each(func(_ int, s *goquery.Selection) {
			if id != "" {
				return
			}
			if href, ok := s.Attr("href"); ok {
				if u, parseErr := url.Parse(href); parseErr == nil {
					id = u.Query().Get("id")
				}
			}
		})
		if id != "" {
			core.SendJSON(core.OutputEvent{Type: "log", Msg: fmt.Sprintf("[IMX] found gallery ID in body: %s", id)})
			return id, nil
		}
	}
	return "0", fmt.Errorf("failed to extract gallery ID from URL: %s", finalURL)
}

func (m *Module) doRequest(ctx context.Context, method, urlStr string, body io.Reader, contentType string) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, method, urlStr, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", core.DefaultUserAgent)
	req.Header.Set("Referer", "https://imx.to/")
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	return m.client.Do(req)
}

// SizeID maps a human-readable thumbnail size string to the IMX size ID.
func SizeID(s string) string {
	m := map[string]string{"100": "1", "150": "6", "180": "2", "250": "3", "300": "4"}
	if v, ok := m[s]; ok {
		return v
	}
	return "2"
}

// FormatID maps a human-readable thumbnail format string to the IMX format ID.
func FormatID(s string) string {
	m := map[string]string{"Fixed Width": "1", "Fixed Height": "4", "Proportional": "2", "Square": "3"}
	if v, ok := m[s]; ok {
		return v
	}
	return "1"
}

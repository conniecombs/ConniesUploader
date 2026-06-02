// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

// Package turbo implements the TurboImageHost service module.
package turbo

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/textproto"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"

	"github.com/conniecombs/GolangVersion/core"
)

const ServiceID = "turboimagehost"

// Module is the self-contained TurboImageHost service plugin.
// It discovers and caches the upload endpoint after login.
type Module struct {
	client *http.Client

	mu       sync.RWMutex
	endpoint string
}

// New constructs a Turbo module wired to the shared HTTP client.
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
	needsLogin := m.endpoint == ""
	endp := m.endpoint
	m.mu.RUnlock()

	if needsLogin {
		m.doLogin(job.Creds)
		m.mu.RLock()
		endp = m.endpoint
		m.mu.RUnlock()
	}
	if endp == "" {
		endp = "https://www.turboimagehost.com/upload_html5.tu"
	}

	fi, err := os.Stat(fp)
	if err != nil {
		return "", "", err
	}

	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)
	go func() {
		defer pw.Close()
		defer writer.Close()

		h := make(textproto.MIMEHeader)
		h.Set("Content-Disposition", fmt.Sprintf(`form-data; name="qqfile"; filename="%s"`, core.QuoteEscape(filepath.Base(fp))))
		h.Set("Content-Type", "application/octet-stream")
		part, _ := writer.CreatePart(h)

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

		_ = writer.WriteField("qquuid", core.RandomString(32))
		_ = writer.WriteField("qqfilename", filepath.Base(fp))
		_ = writer.WriteField("qqtotalfilesize", fmt.Sprintf("%d", fi.Size()))
		_ = writer.WriteField("imcontent", job.Config["turbo_content"])
		_ = writer.WriteField("thumb_size", job.Config["turbo_thumb"])
	}()

	resp, err := m.doRequest(ctx, "POST", endp, pr, writer.FormDataContentType())
	if err != nil {
		return "", "", err
	}
	raw, _ := io.ReadAll(resp.Body)
	_ = resp.Body.Close()

	var res struct {
		Success bool   `json:"success"`
		NewURL  string `json:"newUrl"`
		ID      string `json:"id"`
	}
	_ = json.Unmarshal(raw, &res)

	if !res.Success {
		return "", "", fmt.Errorf("turbo upload failed")
	}
	if res.NewURL != "" {
		return m.scrapeBBCode(res.NewURL)
	}
	if res.ID != "" {
		u := fmt.Sprintf("https://www.turboimagehost.com/p/%s/%s.html", res.ID, filepath.Base(fp))
		return u, u, nil
	}
	return "", "", fmt.Errorf("turbo upload: no URL in response")
}

// --- internal ---

func (m *Module) doLogin(creds map[string]string) bool {
	if creds["turbo_user"] != "" {
		v := url.Values{
			"username": {creds["turbo_user"]},
			"password": {creds["turbo_pass"]},
			"login":    {"Login"},
		}
		if r, err := m.doRequest(context.Background(), "POST", "https://www.turboimagehost.com/login", strings.NewReader(v.Encode()), "application/x-www-form-urlencoded"); err == nil {
			_ = r.Body.Close()
		}
	}

	resp, err := m.doRequest(context.Background(), "GET", "https://www.turboimagehost.com/", nil, "")
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)

	m.mu.Lock()
	defer m.mu.Unlock()
	if matches := regexp.MustCompile(`endpoint:\s*'([^']+)'`).FindStringSubmatch(string(b)); len(matches) > 1 {
		m.endpoint = matches[1]
	}
	return m.endpoint != ""
}

func (m *Module) scrapeBBCode(urlStr string) (string, string, error) {
	resp, err := m.doRequest(context.Background(), "GET", urlStr, nil, "")
	if err != nil {
		return urlStr, urlStr, nil
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	re := regexp.MustCompile(`(?i)\[url=["']?(https?://[^"']+)["']?\]\s*\[img\](https?://[^\[]+)\[/img\]\s*\[/url\]`)
	if m := re.FindStringSubmatch(string(b)); len(m) > 2 {
		return m[1], m[2], nil
	}
	return urlStr, urlStr, nil
}

func (m *Module) doRequest(ctx context.Context, method, urlStr string, body io.Reader, contentType string) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, method, urlStr, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", core.DefaultUserAgent)
	req.Header.Set("Referer", "https://www.turboimagehost.com/")
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	return m.client.Do(req)
}

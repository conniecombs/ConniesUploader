// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

// Package vipergirls implements the ViperGirls forum service module.
// Unlike image-hosting modules, this one handles forum login and thread posting.
package vipergirls

import (
	"context"
	"crypto/md5"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"sync"

	"github.com/conniecombs/GolangVersion/core"
)

const ServiceID = "vipergirls.to"

// Module is the self-contained ViperGirls forum plugin.
// It stores the vBulletin security token required for posting.
type Module struct {
	client *http.Client

	mu            sync.RWMutex
	securityToken string
}

// New constructs a ViperGirls module wired to the shared HTTP client.
func New(client *http.Client) *Module {
	return &Module{client: client}
}

func (m *Module) ID() string { return ServiceID }

// LoginForum implements services.ForumService.
// Returns (success, message).
func (m *Module) LoginForum(creds map[string]string) (bool, string) {
	user, pass := creds["vg_user"], creds["vg_pass"]

	// Seed cookies.
	if r, err := m.doRequest(context.Background(), "GET", "https://vipergirls.to/login.php?do=login", nil, ""); err == nil {
		r.Body.Close()
	}

	hasher := md5.New()
	hasher.Write([]byte(pass))
	md5Pass := hex.EncodeToString(hasher.Sum(nil))

	v := url.Values{
		"vb_login_username":      {user},
		"vb_login_md5password":   {md5Pass},
		"vb_login_md5password_utf": {md5Pass},
		"cookieuser":             {"1"},
		"do":                     {"login"},
		"securitytoken":          {"guest"},
	}
	resp, err := m.doRequest(context.Background(), "POST", "https://vipergirls.to/login.php?do=login",
		strings.NewReader(v.Encode()), "application/x-www-form-urlencoded")
	if err != nil {
		return false, fmt.Sprintf("login request failed: %v", err)
	}
	b, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	body := string(b)

	if strings.Contains(body, "Thank you for logging in") {
		if matches := regexp.MustCompile(`SECURITYTOKEN\s*=\s*"([^"]+)"`).FindStringSubmatch(body); len(matches) > 1 {
			m.mu.Lock()
			m.securityToken = matches[1]
			m.mu.Unlock()
		}
		return true, "Login OK"
	}
	return false, "Invalid credentials"
}

// Post implements services.ForumService.
// Returns (success, message).
func (m *Module) Post(config map[string]string) (bool, string) {
	m.mu.RLock()
	token := m.securityToken
	needsRefresh := token == "" || token == "guest"
	m.mu.RUnlock()

	if needsRefresh {
		if resp, err := m.doRequest(context.Background(), "GET", "https://vipergirls.to/forum.php", nil, ""); err == nil {
			b, _ := io.ReadAll(resp.Body)
			resp.Body.Close()
			if matches := regexp.MustCompile(`SECURITYTOKEN\s*=\s*"([^"]+)"`).FindStringSubmatch(string(b)); len(matches) > 1 {
				m.mu.Lock()
				m.securityToken = matches[1]
				token = matches[1]
				m.mu.Unlock()
			}
		}
	}

	threadID := config["thread_id"]
	v := url.Values{
		"message":       {config["message"]},
		"securitytoken": {token},
		"do":            {"postreply"},
		"t":             {threadID},
		"parseurl":      {"1"},
		"emailupdate":   {"9999"},
	}
	postURL := fmt.Sprintf("https://vipergirls.to/newreply.php?do=postreply&t=%s", threadID)
	resp, err := m.doRequest(context.Background(), "POST", postURL, strings.NewReader(v.Encode()), "application/x-www-form-urlencoded")
	if err != nil {
		return false, err.Error()
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	body := string(b)
	finalURL := resp.Request.URL.String()

	if strings.Contains(strings.ToLower(body), "thank you for posting") ||
		strings.Contains(strings.ToLower(body), "redirecting") {
		return true, "Posted"
	}
	if strings.Contains(finalURL, "showthread.php") || strings.Contains(finalURL, "threads/") {
		return true, "Posted (redirected)"
	}
	return false, "Post not confirmed"
}

func (m *Module) doRequest(ctx context.Context, method, urlStr string, body io.Reader, contentType string) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, method, urlStr, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", core.DefaultUserAgent)
	req.Header.Set("Referer", "https://vipergirls.to/forum.php")
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	return m.client.Do(req)
}

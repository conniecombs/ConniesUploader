// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

// Package turbo implements the TurboImageHost service module.
package turbo

import (
	"context"
	"encoding/json"
	"fmt"
	"html"
	"io"
	"mime/multipart"
	"net/http"
	"net/textproto"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"strings"
	"sync"

	"github.com/conniecombs/GolangVersion/core"
)

const (
	ServiceID      = "turboimagehost"
	turboBaseURL   = "https://www.turboimagehost.com/"
	turboLoginURL  = "https://www.turboimagehost.com/login.tu?"
	turboUploadURL = "https://www.turboimagehost.com/upload_html5.tu"
)

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
		if !m.doLogin(job.Creds) && strings.TrimSpace(job.Creds["turbo_user"]) != "" {
			return "", "", fmt.Errorf("turbo login failed")
		}
		m.mu.RLock()
		endp = m.endpoint
		m.mu.RUnlock()
	}
	if endp == "" {
		endp = turboUploadURL
	}

	fi, err := os.Stat(fp)
	if err != nil {
		return "", "", err
	}
	uploadID := turboUploadID(job.Config)

	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)
	go func() {
		defer pw.Close()
		defer writer.Close()

		_ = writer.WriteField("upload_id", uploadID)
		_ = writer.WriteField("qquuid", core.RandomString(32))
		_ = writer.WriteField("qqfilename", filepath.Base(fp))
		_ = writer.WriteField("qqtotalfilesize", fmt.Sprintf("%d", fi.Size()))
		_ = writer.WriteField("imcontent", turboContentValue(job.Config))
		_ = writer.WriteField("thumb_size", turboThumbSize(job.Config))
		if turboConfigEnabled(job.Config, "turbo_gallery_create", "gallery_create") {
			_ = writer.WriteField("galleryC", "1")
			if name := strings.TrimSpace(firstConfigValue(job.Config, "turbo_gallery_name", "gallery_name", "selected_gallery_name")); name != "" {
				_ = writer.WriteField("galleryN", name)
			}
		} else if galleryID := strings.TrimSpace(firstConfigValue(job.Config, "turbo_gallery_id", "gallery_id")); galleryID != "" {
			_ = writer.WriteField("album", galleryID)
		}

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
		pw2 := core.NewProgressWriter(part, fi.Size(), fp, job.ID)
		if _, err := io.Copy(pw2, f); err != nil {
			pw.CloseWithError(err)
			return
		}
	}()

	resp, err := m.doRequest(ctx, "POST", endp, pr, writer.FormDataContentType())
	if err != nil {
		return "", "", err
	}
	raw, _ := io.ReadAll(resp.Body)
	_ = resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", "", fmt.Errorf("turbo upload HTTP %d: %s", resp.StatusCode, responseSnippet(raw))
	}

	var res struct {
		Success bool   `json:"success"`
		NewURL  string `json:"newUrl"`
		NewURL2 string `json:"new_url"`
		ID      string `json:"id"`
		Error   string `json:"error"`
		Message string `json:"message"`
	}
	if err := json.Unmarshal(raw, &res); err != nil {
		return "", "", fmt.Errorf("turbo upload returned invalid JSON: %w: %s", err, responseSnippet(raw))
	}

	if !res.Success {
		if msg := strings.TrimSpace(firstNonEmpty(res.Error, res.Message)); msg != "" {
			return "", "", fmt.Errorf("turbo upload failed: %s", msg)
		}
		return "", "", fmt.Errorf("turbo upload failed: %s", responseSnippet(raw))
	}
	if res.NewURL == "" {
		res.NewURL = res.NewURL2
	}
	if res.NewURL != "" {
		return m.scrapeBBCode(resolveTurboURL(res.NewURL), filepath.Base(fp))
	}
	if res.ID != "" {
		u := fmt.Sprintf("https://www.turboimagehost.com/p/%s/%s.html", res.ID, filepath.Base(fp))
		return u, u, nil
	}
	return "", "", fmt.Errorf("turbo upload: no URL in response: %s", responseSnippet(raw))
}

// --- internal ---

func (m *Module) doLogin(creds map[string]string) bool {
	username := strings.TrimSpace(creds["turbo_user"])
	if username != "" {
		v := url.Values{
			"username": {username},
			"password": {creds["turbo_pass"]},
			"remember": {"y"},
			"login":    {"Login"},
		}
		r, err := m.doRequest(context.Background(), "POST", turboLoginURL, strings.NewReader(v.Encode()), "application/x-www-form-urlencoded")
		if err != nil {
			return false
		}
		_ = r.Body.Close()
	}

	resp, err := m.doRequest(context.Background(), "GET", turboBaseURL, nil, "")
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
	if m.endpoint == "" {
		return false
	}
	if username != "" {
		return turboAuthenticated(string(b), username)
	}
	return true
}

func (m *Module) scrapeBBCode(urlStr, fileName string) (string, string, error) {
	resp, err := m.doRequest(context.Background(), "GET", urlStr, nil, "")
	if err != nil {
		return urlStr, urlStr, nil
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	if imageURL, thumbURL, ok := extractTurboResultLink(string(b), fileName); ok {
		return imageURL, thumbURL, nil
	}
	if strings.Contains(urlStr, "html5_upload_result.tu") {
		return "", "", fmt.Errorf("turbo result page did not contain an image link for %s", fileName)
	}
	return urlStr, urlStr, nil
}

func (m *Module) doRequest(ctx context.Context, method, urlStr string, body io.Reader, contentType string) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, method, urlStr, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", core.DefaultUserAgent)
	req.Header.Set("Referer", turboBaseURL)
	req.Header.Set("Accept", "application/json, text/html;q=0.9, */*;q=0.8")
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	return m.client.Do(req)
}

func firstConfigValue(config map[string]string, keys ...string) string {
	for _, key := range keys {
		if value := strings.TrimSpace(config[key]); value != "" {
			return value
		}
	}
	return ""
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}

func turboUploadID(config map[string]string) string {
	if uploadID := firstConfigValue(config, "turbo_upload_id", "upload_id"); uploadID != "" {
		return uploadID
	}
	return core.RandomString(20)
}

func turboContentValue(config map[string]string) string {
	raw := strings.ToLower(firstConfigValue(config, "content_type", "turbo_content", "imcontent"))
	switch raw {
	case "adult", "18", "true":
		return "adult"
	case "all", "safe", "family", "family safe", "0", "1":
		return "all"
	default:
		return "all"
	}
}

func turboThumbSize(config map[string]string) string {
	value := firstConfigValue(config, "thumbnail_size", "turbo_thumb", "thumb_size")
	if value == "" {
		return "150"
	}
	return value
}

func turboConfigEnabled(config map[string]string, keys ...string) bool {
	value := strings.ToLower(firstConfigValue(config, keys...))
	return value == "1" || value == "true" || value == "yes" || value == "on"
}

func turboAuthenticated(rawHTML string, username string) bool {
	lowerHTML := strings.ToLower(rawHTML)
	if !strings.Contains(lowerHTML, "logout.tu") && !strings.Contains(lowerHTML, "log out") {
		return false
	}
	username = strings.ToLower(strings.TrimSpace(username))
	return username == "" || strings.Contains(lowerHTML, username)
}

type turboResultLink struct {
	imageURL string
	thumbURL string
	fileName string
}

func extractTurboResultLink(rawHTML string, fileName string) (string, string, bool) {
	links := append(extractTurboBBCodeLinks(rawHTML), extractTurboThumbLinks(rawHTML)...)
	if len(links) == 0 {
		return "", "", false
	}

	if fileName != "" {
		for _, link := range links {
			if turboLinkMatchesFile(link, fileName) {
				return link.imageURL, link.thumbURL, true
			}
		}
	}
	if len(links) == 1 {
		return links[0].imageURL, links[0].thumbURL, true
	}
	return "", "", false
}

func extractTurboBBCodeLinks(rawHTML string) []turboResultLink {
	text := html.UnescapeString(rawHTML)
	re := regexp.MustCompile(`(?is)\[url=(?:"([^"]+)"|'([^']+)'|([^\]\s]+))\]\s*\[img\]([^\[]+)\[/img\]\s*\[/url\]`)
	matches := re.FindAllStringSubmatch(text, -1)
	links := make([]turboResultLink, 0, len(matches))
	for _, match := range matches {
		imageURL := strings.TrimSpace(firstNonEmpty(match[1], match[2], match[3]))
		thumbURL := strings.TrimSpace(match[4])
		if imageURL == "" || thumbURL == "" {
			continue
		}
		links = append(links, turboResultLink{
			imageURL: resolveTurboURL(imageURL),
			thumbURL: resolveTurboURL(thumbURL),
		})
	}
	return links
}

func extractTurboThumbLinks(rawHTML string) []turboResultLink {
	divRe := regexp.MustCompile(`(?is)<div\b[^>]*\bid=["']im_[^"']+["'][^>]*>.*?</div>`)
	thumbRe := regexp.MustCompile(`(?is)background-image\s*:\s*url\((?:'|")?([^)'"]+)`)
	blocks := divRe.FindAllString(rawHTML, -1)
	links := make([]turboResultLink, 0, len(blocks))
	for _, block := range blocks {
		imageURL := turboHTMLAttr(block, "href")
		if imageURL == "" {
			continue
		}
		thumbURL := ""
		if match := thumbRe.FindStringSubmatch(block); len(match) > 1 {
			thumbURL = html.UnescapeString(strings.TrimSpace(match[1]))
		}
		links = append(links, turboResultLink{
			imageURL: resolveTurboURL(imageURL),
			thumbURL: resolveTurboURL(thumbURL),
			fileName: html.UnescapeString(strings.TrimSpace(turboHTMLAttr(block, "title"))),
		})
	}
	return links
}

func turboHTMLAttr(rawHTML string, attr string) string {
	re := regexp.MustCompile(`(?is)\b` + regexp.QuoteMeta(attr) + `\s*=\s*(?:"([^"]*)"|'([^']*)')`)
	if match := re.FindStringSubmatch(rawHTML); len(match) > 2 {
		return html.UnescapeString(strings.TrimSpace(firstNonEmpty(match[1], match[2])))
	}
	return ""
}

func turboLinkMatchesFile(link turboResultLink, fileName string) bool {
	expected := strings.ToLower(strings.TrimSpace(fileName))
	if expected == "" {
		return false
	}
	for _, candidate := range turboFilenameCandidates(link) {
		if candidate == "" {
			continue
		}
		normalized := strings.ToLower(strings.TrimSpace(candidate))
		if decoded, err := url.PathUnescape(normalized); err == nil {
			normalized = decoded
		}
		if normalized == expected || strings.HasSuffix(normalized, "_"+expected) || strings.Contains(normalized, expected) {
			return true
		}
	}
	return false
}

func turboFilenameCandidates(link turboResultLink) []string {
	candidates := []string{link.fileName}
	for _, rawURL := range []string{link.imageURL, link.thumbURL} {
		if rawURL == "" {
			continue
		}
		parsed, err := url.Parse(rawURL)
		if err != nil {
			candidates = append(candidates, path.Base(rawURL))
			continue
		}
		candidates = append(candidates, path.Base(parsed.Path))
	}
	return candidates
}

func resolveTurboURL(rawURL string) string {
	rawURL = strings.TrimSpace(rawURL)
	if rawURL == "" {
		return ""
	}
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return rawURL
	}
	if parsed.IsAbs() {
		return parsed.String()
	}
	base, err := url.Parse(turboBaseURL)
	if err != nil {
		return rawURL
	}
	return base.ResolveReference(parsed).String()
}

func responseSnippet(raw []byte) string {
	text := strings.TrimSpace(string(raw))
	text = strings.ReplaceAll(text, "\r", " ")
	text = strings.ReplaceAll(text, "\n", " ")
	text = strings.Join(strings.Fields(text), " ")
	if len(text) > 500 {
		text = text[:500] + "..."
	}
	if text == "" {
		return "empty response"
	}
	return text
}

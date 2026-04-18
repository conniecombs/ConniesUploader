// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

// Package pixhost implements the Pixhost.to image-hosting service module.
package pixhost

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

	"github.com/conniecombs/GolangVersion/core"
)

const ServiceID = "pixhost.to"

// Module is the self-contained Pixhost.to service plugin.
// Pixhost is stateless — no login required.
type Module struct {
	client *http.Client
}

// New constructs a Pixhost module wired to the shared HTTP client.
func New(client *http.Client) *Module {
	return &Module{client: client}
}

func (m *Module) ID() string { return ServiceID }

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

		part, _ := writer.CreateFormFile("img", filepath.Base(fp))
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

		_ = writer.WriteField("content_type", job.Config["pix_content"])
		_ = writer.WriteField("max_th_size", job.Config["pix_thumb"])
		if h := job.Config["gallery_hash"]; h != "" {
			_ = writer.WriteField("gallery_hash", h)
		}
	}()

	req, _ := http.NewRequestWithContext(ctx, "POST", "https://api.pixhost.to/images", pr)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("User-Agent", core.DefaultUserAgent)

	resp, err := m.client.Do(req)
	if err != nil {
		return "", "", err
	}
	defer resp.Body.Close()

	raw, _ := io.ReadAll(resp.Body)
	var res struct {
		Show string `json:"show_url"`
		Th   string `json:"th_url"`
	}
	_ = json.Unmarshal(raw, &res)
	if res.Show == "" {
		return "", "", fmt.Errorf("pixhost upload failed")
	}
	return res.Show, res.Th, nil
}

// CreateGallery implements services.GalleryCreator.
func (m *Module) CreateGallery(_ map[string]string, name string) (string, interface{}, error) {
	data, err := m.createGallery(name)
	if err != nil {
		return "", nil, err
	}
	return data["gallery_hash"], data, nil
}

// FinalizeGallery implements services.GalleryFinalizer.
func (m *Module) FinalizeGallery(config map[string]string) error {
	uploadHash := config["gallery_upload_hash"]
	galleryHash := config["gallery_hash"]
	if uploadHash == "" || galleryHash == "" {
		return fmt.Errorf("missing gallery hashes")
	}

	finalizeURL := fmt.Sprintf("https://api.pixhost.to/galleries/%s/finalize", galleryHash)
	body := url.Values{}
	body.Set("gallery_upload_hash", uploadHash)

	req, _ := http.NewRequest("POST", finalizeURL, strings.NewReader(body.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Accept", "application/json")
	req.Header.Set("User-Agent", core.DefaultUserAgent)

	resp, err := m.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		b, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("finalize failed HTTP %d: %s", resp.StatusCode, string(b))
	}
	return nil
}

func (m *Module) createGallery(name string) (map[string]string, error) {
	v := url.Values{}
	v.Set("title", name)

	req, _ := http.NewRequest("POST", "https://api.pixhost.to/galleries", strings.NewReader(v.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("User-Agent", core.DefaultUserAgent)

	resp, err := m.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var result struct {
		GalleryHash       string `json:"gallery_hash"`
		GalleryUploadHash string `json:"gallery_upload_hash"`
	}
	_ = json.NewDecoder(resp.Body).Decode(&result)
	if result.GalleryHash == "" {
		return nil, fmt.Errorf("pixhost gallery creation failed")
	}
	return map[string]string{
		"gallery_hash":        result.GalleryHash,
		"gallery_upload_hash": result.GalleryUploadHash,
	}, nil
}

// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package pixhost

import (
	"context"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/conniecombs/GolangVersion/core"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(req *http.Request) (*http.Response, error) {
	return f(req)
}

func jsonResponse(req *http.Request, statusCode int, body string) *http.Response {
	return &http.Response{
		StatusCode: statusCode,
		Header:     http.Header{"Content-Type": []string{"application/json; charset=utf-8"}},
		Body:       io.NopCloser(strings.NewReader(body)),
		Request:    req,
	}
}

func TestCreateGalleryUsesPixhostAPIContract(t *testing.T) {
	module := New(&http.Client{
		Transport: roundTripFunc(func(req *http.Request) (*http.Response, error) {
			if req.Method != http.MethodPost {
				t.Fatalf("method = %s, want POST", req.Method)
			}
			if req.URL.String() != pixhostAPIBase+"/galleries" {
				t.Fatalf("url = %s", req.URL.String())
			}
			if got := req.Header.Get("Accept"); got != "application/json" {
				t.Fatalf("Accept = %q, want application/json", got)
			}

			raw, err := io.ReadAll(req.Body)
			if err != nil {
				t.Fatal(err)
			}
			form, err := url.ParseQuery(string(raw))
			if err != nil {
				t.Fatal(err)
			}
			if got := form.Get("gallery_name"); got != "Test Gallery" {
				t.Fatalf("gallery_name = %q, want Test Gallery", got)
			}
			if got := form.Get("title"); got != "" {
				t.Fatalf("title should not be sent, got %q", got)
			}

			return jsonResponse(req, http.StatusOK, `{
				"gallery_name":"Test Gallery",
				"gallery_hash":"abc123",
				"gallery_url":"https://pixhost.to/gallery/abc123",
				"gallery_upload_hash":"upload456"
			}`), nil
		}),
	})

	id, data, err := module.CreateGallery(nil, " Test Gallery ")
	if err != nil {
		t.Fatalf("CreateGallery returned error: %v", err)
	}
	if id != "abc123" {
		t.Fatalf("id = %q, want abc123", id)
	}
	got, ok := data.(map[string]string)
	if !ok {
		t.Fatalf("data type = %T, want map[string]string", data)
	}
	if got["gallery_upload_hash"] != "upload456" {
		t.Fatalf("gallery_upload_hash = %q", got["gallery_upload_hash"])
	}
	if got["gallery_url"] != "https://pixhost.to/gallery/abc123" {
		t.Fatalf("gallery_url = %q", got["gallery_url"])
	}
}

func TestUploadIncludesGalleryUploadHash(t *testing.T) {
	tmp := t.TempDir()
	imagePath := filepath.Join(tmp, "image.jpg")
	if err := os.WriteFile(imagePath, []byte("fake image"), 0o600); err != nil {
		t.Fatal(err)
	}

	module := New(&http.Client{
		Transport: roundTripFunc(func(req *http.Request) (*http.Response, error) {
			if req.URL.String() != pixhostAPIBase+"/images" {
				t.Fatalf("url = %s", req.URL.String())
			}
			if got := req.Header.Get("Accept"); got != "application/json" {
				t.Fatalf("Accept = %q, want application/json", got)
			}
			if err := req.ParseMultipartForm(1024 * 1024); err != nil {
				t.Fatal(err)
			}
			if got := req.FormValue("gallery_hash"); got != "abc123" {
				t.Fatalf("gallery_hash = %q, want abc123", got)
			}
			if got := req.FormValue("gallery_upload_hash"); got != "upload456" {
				t.Fatalf("gallery_upload_hash = %q, want upload456", got)
			}

			return jsonResponse(req, http.StatusOK, `{
				"name":"image.jpg",
				"show_url":"https://pixhost.to/show/1/image.jpg",
				"th_url":"https://t1.pixhost.to/thumbs/1/image.jpg"
			}`), nil
		}),
	})

	job := &core.JobRequest{
		Config: map[string]string{
			"pix_content":         "0",
			"pix_thumb":           "200",
			"gallery_hash":        "abc123",
			"gallery_upload_hash": "upload456",
		},
	}
	viewer, thumb, err := module.Upload(context.Background(), imagePath, job)
	if err != nil {
		t.Fatalf("Upload returned error: %v", err)
	}
	if viewer == "" || thumb == "" {
		t.Fatalf("expected viewer and thumb URLs, got viewer=%q thumb=%q", viewer, thumb)
	}
}

func TestCreateGalleryRejectsEmptyNameWithoutRequest(t *testing.T) {
	called := false
	module := New(&http.Client{
		Transport: roundTripFunc(func(req *http.Request) (*http.Response, error) {
			called = true
			return jsonResponse(req, http.StatusOK, `{}`), nil
		}),
	})

	_, _, err := module.CreateGallery(nil, "  ")
	if err == nil {
		t.Fatal("expected error for empty gallery name")
	}
	if called {
		t.Fatal("empty gallery name should not make an API request")
	}
}

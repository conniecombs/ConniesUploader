// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package main

import (
	"bytes"
	"encoding/binary"
	"hash/crc32"
	"image"
	"image/color"
	"image/png"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"github.com/conniecombs/GolangVersion/core"
)

func TestHandleHttpRequestResetCookiesStartsFresh(t *testing.T) {
	var sawCookieOnB bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/a":
			http.SetCookie(w, &http.Cookie{Name: "session", Value: "old"})
		case "/b":
			if _, err := r.Cookie("session"); err == nil {
				sawCookieOnB = true
			}
		}
		_, _ = w.Write([]byte("ok"))
	}))
	defer server.Close()

	oldClient := client
	client = server.Client()
	client.Jar = core.NewSwappableJar()
	defer func() { client = oldClient }()

	captureSidecarEvents(t, func() {
		handleHttpRequest(JobRequest{Action: "http_request", Service: "t.test",
			GenericSpec: &core.GenericHttpRequestSpec{URL: server.URL + "/a", UseCookies: true}})
		handleHttpRequest(JobRequest{Action: "http_request", Service: "t.test",
			GenericSpec: &core.GenericHttpRequestSpec{URL: server.URL + "/b", UseCookies: true, ResetCookies: true}})
	})
	if sawCookieOnB {
		t.Fatalf("second request carried the old session cookie despite reset_cookies")
	}
}

func oversizedPNG(t *testing.T) []byte {
	t.Helper()
	var buf bytes.Buffer
	img := image.NewRGBA(image.Rect(0, 0, 1, 1))
	img.Set(0, 0, color.White)
	if err := png.Encode(&buf, img); err != nil {
		t.Fatalf("png encode: %v", err)
	}
	data := buf.Bytes()
	// IHDR chunk: length(4) at 8, type(4) at 12, data(13) at 16, crc(4) at 29.
	binary.BigEndian.PutUint32(data[16:20], 8000)
	binary.BigEndian.PutUint32(data[20:24], 8000)
	binary.BigEndian.PutUint32(data[29:33], crc32.ChecksumIEEE(data[12:29]))
	return data
}

func TestGenerateThumbRejectsOversizedImage(t *testing.T) {
	path := filepath.Join(t.TempDir(), "huge.png")
	if err := os.WriteFile(path, oversizedPNG(t), 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}
	events := captureSidecarEvents(t, func() {
		handleGenerateThumb(JobRequest{Action: "generate_thumb", Files: []string{path}, Config: map[string]string{"width": "100"}})
	})
	errors := eventsOfType(events, "error")
	if len(errors) != 1 || errors[0].Msg != "Image too large to preview" {
		t.Fatalf("events = %+v, want one 'Image too large to preview' error", events)
	}
}

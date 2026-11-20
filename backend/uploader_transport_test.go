// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/conniecombs/GolangVersion/core"
)

// reset_cookies on a forum login must not drop an image host's session.
func TestResetCookiesKeepsOtherSitesSessions(t *testing.T) {
	var galleryCookie string
	imageHost := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/login":
			http.SetCookie(w, &http.Cookie{Name: "xfss", Value: "image-session", Path: "/"})
		case "/galleries":
			if cookie, err := r.Cookie("xfss"); err == nil {
				galleryCookie = cookie.Value
			}
		}
		_, _ = w.Write([]byte("ok"))
	}))
	defer imageHost.Close()
	forum := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("ok"))
	}))
	defer forum.Close()
	// Cookies ignore ports, so give the two local hosts different names.
	forumURL := strings.Replace(forum.URL, "127.0.0.1", "localhost", 1)

	oldClient := client
	client = &http.Client{Jar: core.NewSwappableJar()}
	defer func() { client = oldClient }()

	request := func(url string, reset bool) {
		handleHttpRequest(JobRequest{Action: "http_request", Service: "t.test",
			GenericSpec: &core.GenericHttpRequestSpec{URL: url, UseCookies: true, ResetCookies: reset}})
	}
	captureSidecarEvents(t, func() {
		request(imageHost.URL+"/login", false)
		request(forumURL+"/login.php", true)
		request(imageHost.URL+"/galleries", false)
	})
	if galleryCookie != "image-session" {
		t.Fatalf("image host session after forum login = %q, want image-session", galleryCookie)
	}
}

// deadlineRecorder answers every upload and records whether the request
// context carried a deadline.
type deadlineRecorder struct{ deadlines chan bool }

func (d deadlineRecorder) RoundTrip(req *http.Request) (*http.Response, error) {
	_, _ = io.Copy(io.Discard, req.Body)
	_ = req.Body.Close()
	_, hasDeadline := req.Context().Deadline()
	d.deadlines <- hasDeadline
	return &http.Response{
		StatusCode: http.StatusOK,
		Header:     http.Header{"Content-Type": {"application/json"}},
		Body:       io.NopCloser(strings.NewReader(`{"data":{"image_url":"u","thumbnail_url":"t"}}`)),
		Request:    req,
	}, nil
}

// An upload must not run under a wall-clock deadline: a big file on a slow
// uplink needs longer than any fixed limit. Stalls are caught instead.
func TestUploadRequestHasNoWallClockDeadline(t *testing.T) {
	path := filepath.Join(t.TempDir(), "img.jpg")
	if err := os.WriteFile(path, []byte("jpeg-bytes"), 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}
	recorder := deadlineRecorder{deadlines: make(chan bool, 1)}
	oldClient := client
	client = &http.Client{Timeout: time.Minute, Transport: recorder}
	defer func() { client = oldClient }()

	job := uploadJobForServer(t, "http://upload.test", "b-deadline")
	job.Files = []string{path}

	events := captureSidecarEvents(t, func() { handleJob(job) })

	select {
	case hasDeadline := <-recorder.deadlines:
		if hasDeadline {
			t.Fatal("upload request carried a wall-clock deadline")
		}
	default:
		t.Fatalf("upload request never reached the transport; events=%+v", events)
	}
	if got := len(eventsOfType(events, "result")); got != 1 {
		t.Fatalf("result events = %d, want 1; events=%+v", got, events)
	}
}

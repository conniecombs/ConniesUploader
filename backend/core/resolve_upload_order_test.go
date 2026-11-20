// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

// lossySessionHost is the sessionHost of batch_resolve_test.go (one shared
// session listing every stored image in upload order, links without file
// names), except that it can misbehave on chosen uploads and list new images
// late.
type lossySessionHost struct {
	mu       sync.Mutex
	session  []string
	contents map[string]string
	uploads  int
	// misbehave maps the 1-based upload number to what the host does:
	// "drop" stores the image, then closes the connection without an answer;
	// "502" stores it, then answers 502 (a gateway error after the backend
	// stored the file); "nolink" stores it, then answers 200 without the
	// expected field; "refuse" answers 403 without storing it.
	misbehave map[int]string
	// lateListing hides a successful upload's image from the first look at
	// the result page after it.
	lateListing bool
	hidden      string
	server      *httptest.Server
}

func newLossySessionHost(t *testing.T, misbehave map[int]string) *lossySessionHost {
	h := &lossySessionHost{contents: map[string]string{}, misbehave: misbehave}
	h.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/upload":
			file, _, err := r.FormFile("files[0]")
			if err != nil {
				http.Error(w, "bad", http.StatusBadRequest)
				return
			}
			data, _ := io.ReadAll(file)
			h.mu.Lock()
			h.uploads++
			mode := h.misbehave[h.uploads]
			if mode == "refuse" {
				h.mu.Unlock()
				http.Error(w, `{"error":"not allowed"}`, http.StatusForbidden)
				return
			}
			id := fmt.Sprintf("ME%03d", len(h.contents)+1)
			h.session = append(h.session, id)
			h.contents[id] = string(data)
			if mode == "" && h.lateListing {
				h.hidden = id
			}
			h.mu.Unlock()
			switch mode {
			case "drop":
				if conn, _, err := w.(http.Hijacker).Hijack(); err == nil {
					_ = conn.Close()
				}
				return
			case "502":
				http.Error(w, "bad gateway", http.StatusBadGateway)
				return
			case "nolink":
				_, _ = w.Write([]byte(`{"error":"temporarily unavailable"}`))
				return
			}
			_ = json.NewEncoder(w).Encode(map[string]string{"success": h.server.URL + "/complete"})
		case "/complete":
			h.mu.Lock()
			var b strings.Builder
			for _, id := range h.session {
				if id == h.hidden {
					continue
				}
				fmt.Fprintf(&b, "[URL=https://img.example/view/%s][IMG]https://thumbs.example/%s_t.jpg[/IMG][/URL] ", id, id)
			}
			h.hidden = ""
			h.mu.Unlock()
			_, _ = w.Write([]byte(b.String()))
		default:
			http.NotFound(w, r)
		}
	}))
	return h
}

func (h *lossySessionHost) contentFor(link string) string {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.contents[link[strings.LastIndex(link, "/")+1:]]
}

// In upload_order mode the result page also lists the images of uploads that
// failed after the host stored them (a lost answer, a 502 from a gateway that
// was then retried, a 200 without a link). Each file must still get the entry
// of its own last upload attempt, never an earlier attempt's or another
// file's, or else fail.
func TestUploadOrderGivesEachFileItsOwnLastUpload(t *testing.T) {
	cases := []struct {
		name        string
		misbehave   map[int]string
		lateListing bool
		want        []string // entry id per file, "" for a failed file
	}{
		{name: "drop", misbehave: map[int]string{1: "drop"}, want: []string{"", "ME002", "ME003"}},
		{name: "502 then retried", misbehave: map[int]string{1: "502"}, want: []string{"ME002", "ME003", "ME004"}},
		{name: "nolink", misbehave: map[int]string{1: "nolink"}, want: []string{"", "ME002", "ME003"}},
		{name: "refused without storing", misbehave: map[int]string{1: "refuse"}, want: []string{"", "ME001", "ME002"}},
		{name: "drop, listed late", misbehave: map[int]string{1: "drop"}, lateListing: true, want: []string{"", "ME002", "ME003"}},
		{name: "502, listed late", misbehave: map[int]string{1: "502"}, lateListing: true, want: []string{"ME002", "ME003", "ME004"}},
		{name: "two failures in a row", misbehave: map[int]string{2: "drop", 3: "502"}, want: []string{"ME001", "", "ME004"}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			host := newLossySessionHost(t, tc.misbehave)
			host.lateListing = tc.lateListing
			defer host.server.Close()

			files := writeDistinctFiles(t, []string{"a.jpg", "b.jpg", "c.jpg"})
			job := sessionJob(host.server.URL, files)
			for i, fp := range files {
				result, err := ExecuteHttpUploadWithData(context.Background(), host.server.Client(), fp, job)
				if tc.want[i] == "" {
					if err == nil {
						t.Errorf("file %d: got %q, want a failed upload", i, result.URL)
					}
					continue
				}
				if err != nil {
					t.Errorf("file %d: %v", i, err)
					continue
				}
				if host.contentFor(result.URL) != mustReadFile(t, fp) {
					t.Errorf("file %d reported Done with link %q, which is another file's image", i, result.URL)
				}
				if !strings.HasSuffix(result.URL, "/"+tc.want[i]) {
					t.Errorf("file %d got %q, want entry %s", i, result.URL, tc.want[i])
				}
			}
		})
	}
}

// When the page lists more new images than the job's uploads explain, the
// file's own entry cannot be told apart, so the file fails with a clear
// message instead of taking a guess, and later files are not affected.
func TestUploadOrderFailsAFileWhoseEntryIsAmbiguous(t *testing.T) {
	host := newLossySessionHost(t, nil)
	defer host.server.Close()
	host.session = []string{"XX001"}
	host.contents["XX001"] = "an image the job did not upload"

	files := writeDistinctFiles(t, []string{"a.jpg", "b.jpg", "c.jpg"})
	job := sessionJob(host.server.URL, files)
	for i, fp := range files {
		result, err := ExecuteHttpUploadWithData(context.Background(), host.server.Client(), fp, job)
		if i == 0 {
			if err == nil || !strings.Contains(err.Error(), "cannot tell which") {
				t.Fatalf("file 0: got %q, err %v; want a failure that says the entry is ambiguous", result.URL, err)
			}
			continue
		}
		if err != nil {
			t.Fatalf("file %d: %v", i, err)
		}
		if host.contentFor(result.URL) != mustReadFile(t, fp) {
			t.Fatalf("file %d reported Done with link %q, which is another file's image", i, result.URL)
		}
	}
}

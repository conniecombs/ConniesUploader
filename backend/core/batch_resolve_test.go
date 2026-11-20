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
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

const turboLikeLinkExtractor = `(?is)\[url=(?P<image_url>https?://[^\]]+?/p/[0-9]+/(?P<filename>[^/\]]+?)\.html)\]\s*\[img\](?P<thumb_url>https?://[^\]]+?)\[/img\]\s*\[/url\]`

const viewLinkExtractor = `\[URL=(?P<image_url>https://img\.example/view/[^\]]+)\]\[IMG\](?P<thumb_url>https://thumbs\.example/[^\]]+)\[/IMG\]\[/URL\]`

type pageEntry struct {
	id   int
	name string
}

func turboLikePage(entries []pageEntry) string {
	var b strings.Builder
	b.WriteString("<textarea>\n")
	for _, e := range entries {
		fmt.Fprintf(&b, "[URL=https://img.example/p/%d/%s.html][IMG]https://thumbs.example/t/%d_%s[/IMG][/URL]\n", e.id, e.name, e.id, e.name)
	}
	b.WriteString("</textarea>")
	return b.String()
}

func TestBatchResolvePrefersExactFileNames(t *testing.T) {
	cases := []struct {
		name  string
		files []string
		page  []pageEntry
		want  map[string]int // file -> entry id
	}{
		{
			name:  "cover does not take back_cover",
			files: []string{"/in/cover.jpg", "/in/back_cover.jpg"},
			page:  []pageEntry{{1, "back_cover.jpg"}, {2, "cover.jpg"}},
			want:  map[string]int{"/in/cover.jpg": 2, "/in/back_cover.jpg": 1},
		},
		{
			name:  "2.jpg does not take 12.jpg",
			files: []string{"/in/2.jpg", "/in/12.jpg"},
			page:  []pageEntry{{1, "12.jpg"}, {2, "2.jpg"}},
			want:  map[string]int{"/in/2.jpg": 2, "/in/12.jpg": 1},
		},
		{
			name:  "local names are not parsed as URLs",
			files: []string{"/in/Scan #1.jpg", "/in/Scan #2.jpg"},
			page:  []pageEntry{{1, "Scan__2.jpg"}, {2, "Scan__1.jpg"}},
			want:  map[string]int{"/in/Scan #1.jpg": 2, "/in/Scan #2.jpg": 1},
		},
		{
			name:  "percent-encoded page names",
			files: []string{"/in/Scan #1.jpg", "/in/Scan #2.jpg"},
			page:  []pageEntry{{1, url.PathEscape("Scan #2.jpg")}, {2, url.PathEscape("Scan #1.jpg")}},
			want:  map[string]int{"/in/Scan #1.jpg": 2, "/in/Scan #2.jpg": 1},
		},
		{
			name:  "host replaced spaces with underscores",
			files: []string{"/in/imx api.jpg", "/in/imx.jpg"},
			page:  []pageEntry{{1, "imx.jpg"}, {2, "imx_api.jpg"}},
			want:  map[string]int{"/in/imx api.jpg": 2, "/in/imx.jpg": 1},
		},
		{
			name:  "same base name in two folders",
			files: []string{"/in/setA/01.jpg", "/in/setB/01.jpg"},
			page:  []pageEntry{{1, "01.jpg"}, {2, "01.jpg"}},
			want:  map[string]int{"/in/setA/01.jpg": 1, "/in/setB/01.jpg": 2},
		},
		{
			name:  "host prefix falls back to a looser match",
			files: []string{"/in/beach.jpg"},
			page:  []pageEntry{{1, "4411_beach.jpg"}},
			want:  map[string]int{"/in/beach.jpg": 1},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			body := turboLikePage(tc.page)
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				_, _ = w.Write([]byte(body))
			}))
			defer server.Close()

			fileNames := make(map[string]string, len(tc.files))
			for _, fp := range tc.files {
				fileNames[fp] = filepath.Base(fp)
			}
			spec := &BatchResolveSpec{
				ResultURL:     server.URL,
				PollDelaysMs:  []int{1},
				LinkExtractor: turboLikeLinkExtractor,
				FileMatchMode: "filename",
			}
			results, err := ExecuteBatchResolve(context.Background(), server.Client(), spec, tc.files, fileNames)
			if err != nil {
				t.Fatalf("ExecuteBatchResolve: %v", err)
			}
			for fp, wantID := range tc.want {
				got := results[fp][0]
				if !strings.Contains(got, fmt.Sprintf("/p/%d/", wantID)) {
					t.Fatalf("%s resolved to %q, want entry %d (all: %v)", fp, got, wantID, results)
				}
			}
		})
	}
}

func TestBatchResolveFilenameModeWaitsForExactEntryBeforeLooseMatch(t *testing.T) {
	// The page lags: back_cover.jpg is listed before cover.jpg's own entry.
	var mu sync.Mutex
	polls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		polls++
		n := polls
		mu.Unlock()
		entries := []pageEntry{{1, "back_cover.jpg"}}
		if n > 1 {
			entries = append(entries, pageEntry{2, "cover.jpg"})
		}
		_, _ = w.Write([]byte(turboLikePage(entries)))
	}))
	defer server.Close()

	spec := &BatchResolveSpec{
		ResultURL:     server.URL,
		PollDelaysMs:  []int{1, 1},
		LinkExtractor: turboLikeLinkExtractor,
		FileMatchMode: "filename",
	}
	files := []string{"/in/cover.jpg"}
	results, err := ExecuteBatchResolve(context.Background(), server.Client(), spec, files, map[string]string{files[0]: "cover.jpg"})
	if err != nil {
		t.Fatalf("ExecuteBatchResolve: %v", err)
	}
	if got := results[files[0]][0]; !strings.Contains(got, "/p/2/") {
		t.Fatalf("cover.jpg resolved to %q, want its own entry", got)
	}
}

func TestBatchResolveSingleModeNeverGivesOneEntryToTwoFiles(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`[URL=https://img.example/view/A][IMG]https://thumbs.example/A_t.jpg[/IMG][/URL]`))
	}))
	defer server.Close()

	spec := &BatchResolveSpec{
		ResultURL:     server.URL,
		PollDelaysMs:  []int{1},
		LinkExtractor: viewLinkExtractor,
		FileMatchMode: "single",
	}
	files := []string{"/in/a.jpg", "/in/b.jpg"}
	results, err := ExecuteBatchResolve(context.Background(), server.Client(), spec, files, nil)
	if err == nil {
		t.Fatal("expected an error for the file without an entry")
	}
	if len(results) != 1 {
		t.Fatalf("results = %v, want exactly one file resolved", results)
	}
}

// turboLikeHost stores uploads in arrival order and lists them all on one
// result page, the way a shared upload session does.
type turboLikeHost struct {
	mu       sync.Mutex
	uploads  []pageEntry
	contents map[int]string
	server   *httptest.Server
}

func newTurboLikeHost(t *testing.T) *turboLikeHost {
	host := &turboLikeHost{contents: make(map[int]string)}
	host.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/upload":
			file, header, err := r.FormFile("qqfile")
			if err != nil {
				t.Errorf("qqfile missing: %v", err)
				http.Error(w, "bad", http.StatusBadRequest)
				return
			}
			data, _ := io.ReadAll(file)
			host.mu.Lock()
			id := 1000 + len(host.uploads)
			host.uploads = append(host.uploads, pageEntry{id, strings.ReplaceAll(header.Filename, " ", "_")})
			host.contents[id] = string(data)
			host.mu.Unlock()
			_ = json.NewEncoder(w).Encode(map[string]interface{}{"success": true, "newUrl": host.server.URL + "/result"})
		case "/result":
			host.mu.Lock()
			body := turboLikePage(host.uploads)
			host.mu.Unlock()
			_, _ = w.Write([]byte(body))
		default:
			http.NotFound(w, r)
		}
	}))
	return host
}

func (h *turboLikeHost) contentFor(t *testing.T, link string) string {
	t.Helper()
	var id int
	if _, err := fmt.Sscanf(link[strings.Index(link, "/p/")+3:], "%d", &id); err != nil {
		t.Fatalf("link %q has no id", link)
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.contents[id]
}

func turboLikeJob(serverURL string, files []string) *JobRequest {
	return &JobRequest{
		Action:      "http_upload",
		Service:     "example.test",
		Files:       files,
		RetryConfig: fastRetryConfig(),
		HttpSpec: &HttpRequestSpec{
			URL:    serverURL + "/upload",
			Method: http.MethodPost,
			MultipartFields: map[string]MultipartField{
				"qqfile": {Type: "file", Value: files[0]},
			},
			ResponseParser: ResponseParserSpec{Type: "json", URLPath: "newUrl", StatusPath: "success", SuccessValue: "true"},
		},
		ResolveSpec: &BatchResolveSpec{
			ResultURL:     "{url}",
			PollDelaysMs:  []int{5, 5},
			LinkExtractor: turboLikeLinkExtractor,
			FileMatchMode: "filename",
		},
	}
}

func writeDistinctFiles(t *testing.T, names []string) []string {
	t.Helper()
	dir := t.TempDir()
	files := make([]string, len(names))
	for i, name := range names {
		files[i] = writeUploadTestFile(t, dir, name, 32+i)
	}
	return files
}

func TestPerFileResolveGivesEachFileOfAJobItsOwnEntry(t *testing.T) {
	host := newTurboLikeHost(t)
	defer host.server.Close()

	files := writeDistinctFiles(t, []string{"back_cover.jpg", "cover.jpg", "12.jpg", "2.jpg", "setA/01.jpg", "setB/01.jpg", "Scan #1.jpg", "Scan #2.jpg"})
	job := turboLikeJob(host.server.URL, files)
	for _, fp := range files {
		result, err := ExecuteHttpUploadWithData(context.Background(), host.server.Client(), fp, job)
		if err != nil {
			t.Fatalf("%s: %v", fp, err)
		}
		if host.contentFor(t, result.URL) != mustReadFile(t, fp) {
			t.Fatalf("%s got link %q, which is another file's image", fp, result.URL)
		}
	}
}

func TestConcurrentPerFileResolveNeverSharesAnEntry(t *testing.T) {
	host := newTurboLikeHost(t)
	defer host.server.Close()

	files := writeDistinctFiles(t, []string{"a/01.jpg", "b/01.jpg", "c/01.jpg", "d/01.jpg", "cover.jpg", "back_cover.jpg"})
	job := turboLikeJob(host.server.URL, files)
	links := make([]string, len(files))
	var wg sync.WaitGroup
	for i, fp := range files {
		wg.Add(1)
		go func(i int, fp string) {
			defer wg.Done()
			result, err := ExecuteHttpUploadWithData(context.Background(), host.server.Client(), fp, job)
			if err != nil {
				t.Errorf("%s: %v", fp, err)
				return
			}
			links[i] = result.URL
		}(i, fp)
	}
	wg.Wait()

	seen := make(map[string]string)
	for i, link := range links {
		if other, dup := seen[link]; dup {
			t.Fatalf("%s and %s both got %q", other, files[i], link)
		}
		seen[link] = files[i]
		if base := filepath.Base(files[i]); base != "01.jpg" && host.contentFor(t, link) != mustReadFile(t, files[i]) {
			t.Fatalf("%s got link %q, which is another file's image", files[i], link)
		}
	}
}

// sessionHost models an upload session whose result page lists every image of
// the session in upload order, with links that carry no file names.
type sessionHost struct {
	mu        sync.Mutex
	sessions  map[string][]string // session -> image ids
	contents  map[string]string   // image id -> uploaded bytes
	perUpload bool                // each upload opens its own session
	server    *httptest.Server
}

func newSessionHost(t *testing.T, perUpload bool) *sessionHost {
	host := &sessionHost{sessions: make(map[string][]string), contents: make(map[string]string), perUpload: perUpload}
	host.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/upload":
			file, _, err := r.FormFile("files[0]")
			if err != nil {
				t.Errorf("file missing: %v", err)
				http.Error(w, "bad", http.StatusBadRequest)
				return
			}
			data, _ := io.ReadAll(file)
			host.mu.Lock()
			id := fmt.Sprintf("ME%03d", len(host.contents)+1)
			session := "S1"
			if host.perUpload {
				session = "S-" + id
			}
			host.sessions[session] = append(host.sessions[session], id)
			host.contents[id] = string(data)
			host.mu.Unlock()
			_ = json.NewEncoder(w).Encode(map[string]string{"success": host.server.URL + "/complete?session=" + session})
		case "/complete":
			host.mu.Lock()
			var b strings.Builder
			for _, id := range host.sessions[r.URL.Query().Get("session")] {
				fmt.Fprintf(&b, "[URL=https://img.example/view/%s][IMG]https://thumbs.example/%s_t.jpg[/IMG][/URL] ", id, id)
			}
			host.mu.Unlock()
			_, _ = w.Write([]byte(b.String()))
		default:
			http.NotFound(w, r)
		}
	}))
	return host
}

func (h *sessionHost) contentFor(link string) string {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.contents[link[strings.LastIndex(link, "/")+1:]]
}

func sessionJob(serverURL string, files []string) *JobRequest {
	return &JobRequest{
		Action:      "http_upload",
		Service:     "example.test",
		Files:       files,
		RetryConfig: fastRetryConfig(),
		HttpSpec: &HttpRequestSpec{
			URL:    serverURL + "/upload",
			Method: http.MethodPost,
			MultipartFields: map[string]MultipartField{
				"files[0]": {Type: "file", Value: files[0]},
			},
			ResponseParser: ResponseParserSpec{Type: "json", URLPath: "success"},
		},
		ResolveSpec: &BatchResolveSpec{
			ResultURL:     "{url}",
			PollDelaysMs:  []int{5, 5},
			LinkExtractor: viewLinkExtractor,
			FileMatchMode: "upload_order",
		},
	}
}

func TestUploadOrderModeMatchesSharedSessionEntriesByUploadOrder(t *testing.T) {
	for _, perUpload := range []bool{false, true} {
		t.Run(fmt.Sprintf("session_per_upload=%v", perUpload), func(t *testing.T) {
			host := newSessionHost(t, perUpload)
			defer host.server.Close()

			files := writeDistinctFiles(t, []string{"cover.jpg", "a.jpg", "b.jpg", "c.jpg"})
			job := sessionJob(host.server.URL, files)
			for _, fp := range files {
				result, err := ExecuteHttpUploadWithData(context.Background(), host.server.Client(), fp, job)
				if err != nil {
					t.Fatalf("%s: %v", fp, err)
				}
				if host.contentFor(result.URL) != mustReadFile(t, fp) {
					t.Fatalf("%s got link %q, which is another file's image", fp, result.URL)
				}
				if !strings.Contains(result.Thumb, result.URL[strings.LastIndex(result.URL, "/")+1:]) {
					t.Fatalf("%s thumb %q does not belong to link %q", fp, result.Thumb, result.URL)
				}
			}
		})
	}
}

func TestResolveNeedsSequentialUploads(t *testing.T) {
	if !ResolveNeedsSequentialUploads(&BatchResolveSpec{FileMatchMode: "upload_order"}) {
		t.Fatal("upload_order must run a job's uploads one at a time")
	}
	for _, mode := range []string{"", "filename", "contains", "single", "first"} {
		if ResolveNeedsSequentialUploads(&BatchResolveSpec{FileMatchMode: mode}) {
			t.Fatalf("mode %q should not force sequential uploads", mode)
		}
	}
	if ResolveNeedsSequentialUploads(nil) {
		t.Fatal("a job without a resolve spec should not force sequential uploads")
	}
}

func mustReadFile(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path) // #nosec G304 -- test fixture path
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	return string(data)
}

// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"encoding/json"
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

// testdata/turbo_upload_parity.json pins what the legacy Go path reports for
// TurboImageHost's upload answers and result pages, with Turbo's legacy
// response_parser and resolve_spec. frontend/tests/test_turbo_upload_parity.py
// runs the same cases through the plugin's Python parser.

type turboParityAnswer struct {
	Status int    `json:"status"`
	Body   string `json:"body"`
}

// UnmarshalJSON reads a page: a body (status 200) or {"status", "body"}.
func (a *turboParityAnswer) UnmarshalJSON(data []byte) error {
	var body string
	if err := json.Unmarshal(data, &body); err == nil {
		a.Status, a.Body = http.StatusOK, body
		return nil
	}
	type plain turboParityAnswer
	return json.Unmarshal(data, (*plain)(a))
}

type turboParityCase struct {
	Name      string               `json:"name"`
	Files     []string             `json:"files"`
	Upload    turboParityAnswer    `json:"upload"`
	Uploads   []*turboParityAnswer `json:"uploads"`
	Pages     []turboParityAnswer  `json:"pages"`
	ResultURL string               `json:"result_url"`
	Requests  int                  `json:"page_requests"`
	Want      map[string]struct {
		URL        string `json:"url"`
		Thumb      string `json:"thumb"`
		GalleryURL string `json:"gallery_url"`
		Error      string `json:"error"`
	} `json:"want"`
}

type turboParityFixture struct {
	Legacy struct {
		ResponseParser ResponseParserSpec `json:"response_parser"`
		ResolveSpec    BatchResolveSpec   `json:"resolve_spec"`
	} `json:"legacy"`
	Cases []turboParityCase `json:"cases"`
}

// turboParityHost answers every request a case makes, whatever host it names:
// uploads in upload order, result-page requests with the case's pages.
type turboParityHost struct {
	tc      turboParityCase
	mu      sync.Mutex
	posts   int
	gets    int
	fetched []string
}

func (h *turboParityHost) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	h.mu.Lock()
	var answer turboParityAnswer
	if r.Method == http.MethodPost {
		answer = h.tc.Upload
		if h.posts < len(h.tc.Uploads) && h.tc.Uploads[h.posts] != nil {
			answer = *h.tc.Uploads[h.posts]
		}
		h.posts++
	} else {
		answer = h.tc.Pages[min(h.gets, len(h.tc.Pages)-1)]
		h.gets++
		h.fetched = append(h.fetched, r.Header.Get("X-Requested-URL"))
	}
	h.mu.Unlock()
	_, _ = io.Copy(io.Discard, r.Body)
	w.WriteHeader(answer.Status)
	_, _ = w.Write([]byte(answer.Body))
}

// toLocalServer sends every request to the test server, so the legacy spec's
// real host names are kept and never contacted.
type toLocalServer struct{ server *url.URL }

func (t toLocalServer) RoundTrip(req *http.Request) (*http.Response, error) {
	local := req.Clone(req.Context())
	local.Header.Set("X-Requested-URL", req.URL.String())
	local.URL.Scheme, local.URL.Host, local.Host = t.server.Scheme, t.server.Host, t.server.Host
	return http.DefaultTransport.RoundTrip(local)
}

func loadTurboParityFixture(t *testing.T) turboParityFixture {
	t.Helper()
	data, err := os.ReadFile("testdata/turbo_upload_parity.json")
	if err != nil {
		t.Fatalf("read fixture: %v", err)
	}
	var fixture turboParityFixture
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatalf("decode fixture: %v", err)
	}
	return fixture
}

func TestTurboParityLegacyPath(t *testing.T) {
	fixture := loadTurboParityFixture(t)
	if len(fixture.Cases) == 0 {
		t.Fatal("no cases")
	}
	for _, tc := range fixture.Cases {
		t.Run(tc.Name, func(t *testing.T) {
			host := &turboParityHost{tc: tc}
			server := httptest.NewServer(host)
			defer server.Close()
			serverURL, _ := url.Parse(server.URL)
			client := &http.Client{Transport: toLocalServer{serverURL}}

			dir := t.TempDir()
			local := make(map[string]string, len(tc.Files))
			files := make([]string, len(tc.Files))
			for i, fp := range tc.Files {
				files[i] = writeUploadTestFile(t, dir, filepath.FromSlash(strings.TrimPrefix(fp, "/")), 64+i)
				local[fp] = files[i]
			}
			resolve := fixture.Legacy.ResolveSpec
			// The legacy schedule's number of looks, without its waits.
			resolve.PollDelaysMs = make([]int, len(resolve.PollDelaysMs))
			for i := range resolve.PollDelaysMs {
				resolve.PollDelaysMs[i] = 1
			}
			retry := fastRetryConfig()
			retry.RetryableHTTPCodes = nil // the raw path never resends these answers
			job := &JobRequest{
				Action:      "http_upload",
				Service:     "turbo.parity.test",
				Files:       files,
				RetryConfig: retry,
				HttpSpec: &HttpRequestSpec{
					URL:    "https://www.turboimagehost.com/upload_html5.tu",
					Method: http.MethodPost,
					MultipartFields: map[string]MultipartField{
						"qqfile":     {Type: "file", Value: files[0]},
						"qqfilename": {Type: "text", Value: "{filename}"},
					},
					ResponseParser: fixture.Legacy.ResponseParser,
				},
				ResolveSpec: &resolve,
			}

			// One file after another, each resolved right after its own upload.
			for _, fp := range tc.Files {
				want, ok := tc.Want[fp]
				if !ok {
					t.Fatalf("no expectation for %s", fp)
				}
				result, err := ExecuteHttpUploadWithData(context.Background(), client, local[fp], job)
				gotErr := ""
				if err != nil {
					gotErr = err.Error()
				}
				gallery := ""
				if result.Data != nil {
					gallery = result.Data["gallery_url"]
				}
				if result.URL != want.URL || result.Thumb != want.Thumb || gallery != want.GalleryURL || gotErr != want.Error {
					t.Errorf("%s:\n got url=%q thumb=%q gallery=%q err=%q\nwant url=%q thumb=%q gallery=%q err=%q",
						fp, result.URL, result.Thumb, gallery, gotErr, want.URL, want.Thumb, want.GalleryURL, want.Error)
				}
			}
			if len(host.fetched) != tc.Requests {
				t.Errorf("read the result page %d times, want %d", len(host.fetched), tc.Requests)
			}
			for _, fetched := range host.fetched {
				if fetched != tc.ResultURL {
					t.Errorf("read result page %q, want %q", fetched, tc.ResultURL)
				}
			}
		})
	}
}

// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"strings"
	"sync"
	"testing"
)

// The cases in testdata/vipr_parity.json pin what the legacy Go path reports
// for Vipr's pages. frontend/tests/test_vipr_parity.py runs the same cases
// through the Vipr plugin's Python upload path, and checks that legacy_spec
// is the spec the plugin builds, so the two paths are compared on the same
// pages with the same spec.

type viprPage struct {
	Status int    `json:"status"`
	Body   string `json:"body"`
}

type viprParityCase struct {
	Name             string            `json:"name"`
	Login            viprPage          `json:"login"`
	Home             viprPage          `json:"home"`
	Upload           *viprPage         `json:"upload"`
	FollowUp         *viprPage         `json:"follow_up"`
	PostedResultForm map[string]string `json:"posted_result_form"`
	Want             struct {
		URL        string `json:"url"`
		Thumb      string `json:"thumb"`
		GalleryURL string `json:"gallery_url"`
	} `json:"want"`
	LegacyError       string `json:"legacy_error"`
	LegacyErrorPrefix bool   `json:"legacy_error_prefix"`
}

type viprParityFixture struct {
	BaseURL      string            `json:"base_url"`
	File         string            `json:"file"`
	Creds        map[string]string `json:"creds"`
	LegacySpec   json.RawMessage   `json:"legacy_spec"`
	UploadFields map[string]string `json:"upload_fields"`
	UploadQuery  string            `json:"upload_query"`
	Cases        []viprParityCase  `json:"cases"`
}

func loadViprParityFixture(t *testing.T) viprParityFixture {
	t.Helper()
	data, err := os.ReadFile("testdata/vipr_parity.json")
	if err != nil {
		t.Fatalf("read fixture: %v", err)
	}
	var fixture viprParityFixture
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatalf("decode fixture: %v", err)
	}
	return fixture
}

// viprRequests is what the fake Vipr host received.
type viprRequests struct {
	mu          sync.Mutex
	login       map[string]string
	uploadQuery string
	upload      map[string]string
	fileName    string
	resultForm  map[string]string
}

func formValues(values map[string][]string) map[string]string {
	flat := make(map[string]string, len(values))
	for key, value := range values {
		flat[key] = strings.Join(value, ",")
	}
	return flat
}

// viprCaseServer answers like Vipr: POST / op=login, GET / (home page), the
// upload endpoint, and POST / with the upload result form.
func viprCaseServer(t *testing.T, tc viprParityCase, got *viprRequests) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		write := func(page *viprPage) {
			if page == nil {
				t.Errorf("%s: unexpected %s %s", tc.Name, r.Method, r.URL)
				http.NotFound(w, r)
				return
			}
			status := page.Status
			if status == 0 {
				status = http.StatusOK
			}
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			w.WriteHeader(status)
			_, _ = w.Write([]byte(strings.ReplaceAll(page.Body, "{{SERVER}}", "http://"+r.Host)))
		}
		got.mu.Lock()
		defer got.mu.Unlock()
		switch {
		case r.URL.Path == "/" && r.Method == http.MethodGet:
			write(&tc.Home)
		case r.URL.Path == "/" && r.Method == http.MethodPost:
			if err := r.ParseForm(); err != nil {
				t.Errorf("%s: ParseForm: %v", tc.Name, err)
			}
			if r.PostForm.Get("op") == "login" {
				got.login = formValues(r.PostForm)
				write(&tc.Login)
				return
			}
			got.resultForm = formValues(r.PostForm)
			write(tc.FollowUp)
		case r.URL.Path == "/cgi-bin/upload.cgi" && r.Method == http.MethodPost:
			if err := r.ParseMultipartForm(1 << 20); err != nil {
				t.Errorf("%s: ParseMultipartForm: %v", tc.Name, err)
			}
			got.uploadQuery = r.URL.RawQuery
			if r.MultipartForm != nil {
				got.upload = formValues(r.MultipartForm.Value)
				if files := r.MultipartForm.File["file_0"]; len(files) == 1 {
					got.fileName = files[0].Filename
				}
			}
			write(tc.Upload)
		default:
			http.NotFound(w, r)
		}
	}))
}

// viprLegacySpec is the fixture's legacy spec with Vipr's site moved to the
// test server.
func viprLegacySpec(t *testing.T, fixture viprParityFixture, serverURL string) *HttpRequestSpec {
	t.Helper()
	raw := strings.ReplaceAll(string(fixture.LegacySpec), fixture.BaseURL, serverURL+"/")
	var spec HttpRequestSpec
	if err := json.Unmarshal([]byte(raw), &spec); err != nil {
		t.Fatalf("decode legacy_spec: %v", err)
	}
	if spec.PreRequest == nil || spec.PreRequest.FollowUpRequest == nil || spec.ResponseParser.FollowUpRequest == nil {
		t.Fatal("legacy_spec lacks the login chain or the result-form follow-up")
	}
	return &spec
}

func TestViprParityLegacyPath(t *testing.T) {
	fixture := loadViprParityFixture(t)
	if len(fixture.Cases) == 0 {
		t.Fatal("no Vipr parity cases")
	}
	fp := writeUploadTestFile(t, t.TempDir(), filepath.Base(fixture.File), 64)
	uploadQuery := regexp.MustCompile(fixture.UploadQuery)

	for _, tc := range fixture.Cases {
		got := &viprRequests{}
		server := viprCaseServer(t, tc, got)
		job := &JobRequest{
			ID:          "vipr-parity",
			Action:      "http_upload",
			Service:     "vipr.im",
			Files:       []string{fp},
			Creds:       fixture.Creds,
			Config:      map[string]string{},
			RetryConfig: fastRetryConfig(),
			HttpSpec:    viprLegacySpec(t, fixture, server.URL),
		}
		result, err := ExecuteHttpUploadWithData(context.Background(), server.Client(), fp, job)
		server.Close()

		gotErr := ""
		if err != nil {
			gotErr = err.Error()
		}
		wantErr := strings.ReplaceAll(tc.LegacyError, "{{SERVER}}", server.URL)
		errOK := gotErr == wantErr
		if tc.LegacyErrorPrefix {
			errOK = wantErr != "" && strings.HasPrefix(gotErr, wantErr)
		}
		if result.URL != tc.Want.URL || result.Thumb != tc.Want.Thumb || result.Data["gallery_url"] != tc.Want.GalleryURL || !errOK {
			t.Errorf("%s:\n got url=%q thumb=%q gallery=%q err=%q\nwant url=%q thumb=%q gallery=%q err=%q (prefix %v)",
				tc.Name, result.URL, result.Thumb, result.Data["gallery_url"], gotErr,
				tc.Want.URL, tc.Want.Thumb, tc.Want.GalleryURL, wantErr, tc.LegacyErrorPrefix)
		}

		got.mu.Lock()
		wantLogin := map[string]string{"op": "login", "login": fixture.Creds["vipr_user"], "password": fixture.Creds["vipr_pass"]}
		if !reflect.DeepEqual(got.login, wantLogin) {
			t.Errorf("%s: login form = %v, want %v", tc.Name, got.login, wantLogin)
		}
		if tc.Upload != nil {
			if !reflect.DeepEqual(got.upload, fixture.UploadFields) {
				t.Errorf("%s: upload fields = %v, want %v", tc.Name, got.upload, fixture.UploadFields)
			}
			if got.fileName != filepath.Base(fixture.File) {
				t.Errorf("%s: uploaded file name = %q, want %q", tc.Name, got.fileName, filepath.Base(fixture.File))
			}
			if !uploadQuery.MatchString(got.uploadQuery) {
				t.Errorf("%s: upload query = %q, want %s", tc.Name, got.uploadQuery, fixture.UploadQuery)
			}
		} else if got.upload != nil {
			t.Errorf("%s: uploaded although the login failed", tc.Name)
		}
		if tc.PostedResultForm != nil && !reflect.DeepEqual(got.resultForm, tc.PostedResultForm) {
			t.Errorf("%s: result form posted = %v, want %v", tc.Name, got.resultForm, tc.PostedResultForm)
		}
		got.mu.Unlock()
	}
}

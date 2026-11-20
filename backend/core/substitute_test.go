// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync"
	"testing"
)

func TestSubstituteValuesNeverRescansInsertedValues(t *testing.T) {
	got, err := substituteValues("name={filename}&id={upload_id}", map[string]string{
		"filename":  "IMG {final}.jpg",
		"upload_id": "{filename}",
	})
	if err != nil {
		t.Fatalf("substituteValues returned error: %v", err)
	}
	if want := "name=IMG {final}.jpg&id={filename}"; got != want {
		t.Fatalf("substituteValues = %q, want %q", got, want)
	}
}

func TestSubstituteValuesKeepsBraceTextThatNamesNoValue(t *testing.T) {
	for _, values := range []map[string]string{nil, {"sess_id": "S1"}} {
		for _, input := range []string{"Tr0ub{4dor}&3", "Holiday {2024}", "Beach {HQ}", "Set {1}", "pa{ss}"} {
			got, err := substituteValues(input, values)
			if err != nil {
				t.Fatalf("substituteValues(%q) returned error: %v", input, err)
			}
			if got != input {
				t.Fatalf("substituteValues(%q) = %q, want it unchanged", input, got)
			}
		}
	}
}

func TestSubstituteValuesStillFillsKnownTokensNextToLiteralBraces(t *testing.T) {
	got, err := substituteValues("{sess_id}:{HQ}", map[string]string{"sess_id": "S1"})
	if err != nil {
		t.Fatalf("substituteValues returned error: %v", err)
	}
	if got != "S1:{HQ}" {
		t.Fatalf("substituteValues = %q, want S1:{HQ}", got)
	}
}

// Every user-entered value below contains braces: the password and gallery
// title travel in pre_request form fields, the title in a multipart text
// field, and the file name through the {filename} token. All of them must
// reach the host exactly as typed.
func TestUploadSendsUserValuesWithBracesUnchanged(t *testing.T) {
	dir := t.TempDir()
	fp := filepath.Join(dir, "IMG {final}.jpg")
	if err := os.WriteFile(fp, []byte("jpeg-bytes"), 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}

	var mu sync.Mutex
	got := map[string]string{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		switch r.URL.Path {
		case "/login":
			_ = r.ParseForm()
			got["password"] = r.PostFormValue("password")
			got["gallery_title"] = r.PostFormValue("gallery_title")
			_, _ = w.Write([]byte(`<input name="sess_id" value="S1">`))
		case "/upload":
			if err := r.ParseMultipartForm(1 << 20); err != nil {
				t.Errorf("ParseMultipartForm: %v", err)
			}
			got["title"] = r.FormValue("title")
			got["qqfilename"] = r.FormValue("qqfilename")
			got["sess_id"] = r.FormValue("sess_id")
			if f, header, err := r.FormFile("image"); err == nil {
				got["file_name"] = header.Filename
				_, _ = io.Copy(io.Discard, f)
				_ = f.Close()
			}
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"url":"https://img.example/u","thumb":"https://img.example/t"}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	job := &JobRequest{
		ID:      "braces",
		Service: "braces.test",
		Files:   []string{fp},
		HttpSpec: &HttpRequestSpec{
			URL:    server.URL + "/upload",
			Method: http.MethodPost,
			PreRequest: &PreRequestSpec{
				URL:          server.URL + "/login",
				Method:       http.MethodPost,
				FormFields:   map[string]string{"password": "Tr0ub{4dor}&3", "gallery_title": "Beach {HQ}"},
				UseCookies:   true,
				ResponseType: "html",
				ExtractFields: map[string]string{
					"sess_id": "input[name='sess_id']",
				},
			},
			MultipartFields: map[string]MultipartField{
				"image":      {Type: "file", Value: fp},
				"title":      {Type: "text", Value: "Holiday {2024}"},
				"qqfilename": {Type: "text", Value: "{filename}"},
				"sess_id":    {Type: "dynamic", Value: "sess_id"},
			},
			ResponseParser: ResponseParserSpec{Type: "json", URLPath: "url", ThumbPath: "thumb"},
		},
		RetryConfig: &RetryConfig{MaxRetries: 0},
	}

	result, err := ExecuteHttpUploadWithData(context.Background(), server.Client(), fp, job)
	if err != nil {
		t.Fatalf("upload failed: %v", err)
	}
	if result.URL != "https://img.example/u" {
		t.Fatalf("result url = %q", result.URL)
	}
	want := map[string]string{
		"password":      "Tr0ub{4dor}&3",
		"gallery_title": "Beach {HQ}",
		"title":         "Holiday {2024}",
		"qqfilename":    "IMG {final}.jpg",
		"file_name":     "IMG {final}.jpg",
		"sess_id":       "S1",
	}
	mu.Lock()
	defer mu.Unlock()
	for key, value := range want {
		if got[key] != value {
			t.Errorf("host received %s = %q, want %q", key, got[key], value)
		}
	}
}

func TestGenericRequestSendsFormValuesWithBracesUnchanged(t *testing.T) {
	received := make(chan string, 2)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = r.ParseForm()
		received <- r.PostFormValue("gallery_name") + "|" + r.PostFormValue("password")
		_, _ = w.Write([]byte(`{"gallery_hash":"abc"}`))
	}))
	defer server.Close()

	spec := &GenericHttpRequestSpec{
		URL:        server.URL + "/galleries",
		Method:     http.MethodPost,
		FormFields: map[string]string{"gallery_name": "Set {1}", "password": "pa{ss}"},
		UseCookies: true,
	}
	if _, err := ExecuteGenericRequest(context.Background(), server.Client(), spec, nil); err != nil {
		t.Fatalf("ExecuteGenericRequest returned error: %v", err)
	}
	if got := <-received; got != "Set {1}|pa{ss}" {
		t.Fatalf("host received %q, want the values unchanged", got)
	}
}

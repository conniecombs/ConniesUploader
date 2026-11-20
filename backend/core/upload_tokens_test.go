// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"sync"
	"testing"
)

func TestMultipartTextFieldsGetPerFileTokens(t *testing.T) {
	dir := t.TempDir()
	sizes := map[string]int{"small.jpg": 104, "large.jpg": 5004, "mid.jpg": 904}
	var files []string
	for _, name := range []string{"small.jpg", "large.jpg", "mid.jpg"} {
		files = append(files, writeUploadTestFile(t, dir, name, sizes[name]))
	}

	type seen struct{ name, size, uuid string }
	var mu sync.Mutex
	var got []seen
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if err := r.ParseMultipartForm(1 << 20); err != nil {
			t.Errorf("ParseMultipartForm: %v", err)
		}
		mu.Lock()
		got = append(got, seen{r.FormValue("qqfilename"), r.FormValue("qqtotalfilesize"), r.FormValue("qquuid")})
		mu.Unlock()
		_ = json.NewEncoder(w).Encode(map[string]string{"url": "https://img.example/" + r.FormValue("qqfilename")})
	}))
	defer server.Close()

	job := &JobRequest{
		Action:      "http_upload",
		Service:     "example.test",
		Files:       files,
		RetryConfig: fastRetryConfig(),
		HttpSpec: &HttpRequestSpec{
			URL:    server.URL + "/upload",
			Method: http.MethodPost,
			MultipartFields: map[string]MultipartField{
				"qqfile":          {Type: "file", Value: files[0]},
				"qqfilename":      {Type: "text", Value: "{filename}"},
				"qqtotalfilesize": {Type: "text", Value: "{file_size}"},
				"qquuid":          {Type: "text", Value: "{upload_id}"},
			},
			ResponseParser: ResponseParserSpec{Type: "json", URLPath: "url"},
		},
	}
	for _, fp := range files {
		if _, err := ExecuteHttpUploadWithData(context.Background(), server.Client(), fp, job); err != nil {
			t.Fatalf("%s: %v", fp, err)
		}
	}

	uuids := make(map[string]bool)
	for _, s := range got {
		if s.size != strconv.Itoa(sizes[s.name]) {
			t.Fatalf("%s sent qqtotalfilesize=%s, want %d", s.name, s.size, sizes[s.name])
		}
		if s.uuid == "" || uuids[s.uuid] {
			t.Fatalf("%s sent qquuid %q, want a value unique to the file", s.name, s.uuid)
		}
		uuids[s.uuid] = true
	}
	if len(got) != len(files) {
		t.Fatalf("host saw %d uploads, want %d", len(got), len(files))
	}
}

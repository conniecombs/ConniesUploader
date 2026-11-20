// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// A response follow-up that fails is reported like any other refusal of the
// upload: the host's message, shortened, with job credentials redacted, never
// the whole follow-up page. The error still carries the follow-up's status.
func TestResponseFollowUpFailureQuotesAShortRedactedMessage(t *testing.T) {
	const password = "hunter2-Very-Secret"
	long := strings.Repeat("padding ", 200)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/upload":
			_, _ = io.Copy(io.Discard, r.Body)
			_, _ = w.Write([]byte(`<html><body><textarea name="fn">abc</textarea></body></html>`))
		case "/next":
			w.WriteHeader(http.StatusInternalServerError)
			_, _ = w.Write([]byte(`<html><body>login=user password=` + password + ` ` + long + `</body></html>`))
		}
	}))
	defer server.Close()
	fp := writeUploadTestFile(t, t.TempDir(), "a.jpg", 64)
	job := &JobRequest{
		ID:          "followup",
		Action:      "http_upload",
		Service:     "example.test",
		Files:       []string{fp},
		Creds:       map[string]string{"pass": password},
		RetryConfig: fastRetryConfig(),
		HttpSpec: &HttpRequestSpec{
			URL:             server.URL + "/upload",
			Method:          http.MethodPost,
			MultipartFields: map[string]MultipartField{"file": {Type: "file", Value: fp}},
			ResponseParser: ResponseParserSpec{
				Type:    "html",
				URLPath: "regex:(https://x/[a-z]+)",
				FollowUpRequest: &ResponseFollowUpSpec{
					URL:           server.URL + "/next",
					Method:        http.MethodPost,
					ResponseType:  "html",
					ExtractFields: map[string]string{"fn": "textarea[name='fn']"},
					FormFields:    map[string]string{"fn": "{fn}"},
				},
			},
		},
	}
	_, err := ExecuteHttpUploadWithData(context.Background(), server.Client(), fp, job)
	if err == nil {
		t.Fatal("expected failure")
	}
	if strings.Contains(err.Error(), password) {
		t.Errorf("error quotes the job credential unredacted (len %d): %.160s...", len(err.Error()), err.Error())
	}
	if n := len([]rune(err.Error())); n > 400 {
		t.Errorf("error is %d runes long; the whole HTML body is quoted", n)
	}
	if !strings.Contains(err.Error(), "login=user password=[redacted]") {
		t.Errorf("error does not quote the host's redacted message: %v", err)
	}
	var statusErr *HTTPStatusError
	if !errors.As(err, &statusErr) || statusErr.StatusCode != http.StatusInternalServerError {
		t.Errorf("error %v does not carry the follow-up's HTTP 500", err)
	}
}

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

const echoedSessionSecret = "SESS-7f3a9c2b1d"

// sessionEchoServer: "/" is a login page holding a session token; "/upload"
// rejects the upload and quotes the session token back in its JSON message.
func sessionEchoServer() *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/":
			_, _ = w.Write([]byte(`<html><body><form><input name="sess_id" value="` + echoedSessionSecret + `"></form></body></html>`))
		case "/upload":
			_, _ = io.Copy(io.Discard, r.Body)
			w.WriteHeader(http.StatusForbidden)
			_, _ = w.Write([]byte(`{"error":"session ` + echoedSessionSecret + ` is not allowed to upload"}`))
		default:
			http.NotFound(w, r)
		}
	}))
}

func sessionEchoJob(serverURL string, files []string) *JobRequest {
	return &JobRequest{
		ID:          "redact",
		Action:      "http_upload",
		Service:     "example.test",
		Files:       files,
		RetryConfig: fastRetryConfig(),
		HttpSpec: &HttpRequestSpec{
			URL:    serverURL + "/upload",
			Method: http.MethodPost,
			PreRequest: &PreRequestSpec{
				URL:           serverURL + "/",
				Method:        http.MethodGet,
				UseCookies:    true,
				ResponseType:  "html",
				ExtractFields: map[string]string{"sess_id": "input[name='sess_id']"},
			},
			MultipartFields: map[string]MultipartField{
				"file":    {Type: "file", Value: files[0]},
				"sess_id": {Type: "dynamic", Value: "sess_id"},
			},
			ResponseParser: ResponseParserSpec{Type: "json", URLPath: "url"},
		},
	}
}

// Every value the login step extracted is redacted from an upload failure,
// whether pre_request ran once for the job (a multi-file job's shared
// session) or inline for the file (a single-file job, or once_per_file).
func TestUploadFailureRedactsPreRequestValuesOfEveryJobShape(t *testing.T) {
	server := sessionEchoServer()
	defer server.Close()
	dir := t.TempDir()
	a := writeUploadTestFile(t, dir, "a.jpg", 64)
	b := writeUploadTestFile(t, dir, "b.jpg", 65)

	shared := sessionEchoJob(server.URL, []string{a, b})
	if err := PrepareSharedUploadSession(context.Background(), server.Client(), shared); err != nil {
		t.Fatalf("session: %v", err)
	}
	perFile := sessionEchoJob(server.URL, []string{a, b})
	perFile.HttpSpec.PreRequest.OncePerFile = true

	for name, job := range map[string]*JobRequest{
		"shared session":  shared,
		"single-file job": sessionEchoJob(server.URL, []string{a}),
		"once_per_file":   perFile,
	} {
		_, err := ExecuteHttpUploadWithData(context.Background(), server.Client(), a, job)
		if err == nil {
			t.Fatalf("%s: expected the rejected upload to fail", name)
		}
		if strings.Contains(err.Error(), echoedSessionSecret) {
			t.Errorf("%s: error quotes the session token unredacted: %v", name, err)
		}
		if !strings.Contains(err.Error(), "session [redacted] is not allowed") {
			t.Errorf("%s: error does not quote the host's redacted message: %v", name, err)
		}
	}
}

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

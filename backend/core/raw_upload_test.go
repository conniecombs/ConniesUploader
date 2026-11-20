// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"io"
	"mime"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func rawJob(fp string, request *RawUploadRequest, retries *RetryConfig) *JobRequest {
	return &JobRequest{
		ID:           "raw",
		Action:       "http_upload",
		Service:      "raw.test",
		Files:        []string{fp},
		RawResponse:  true,
		FileRequests: map[string]*RawUploadRequest{fp: request},
		RetryConfig:  retries,
	}
}

func rawRequest(url, fp string) *RawUploadRequest {
	return &RawUploadRequest{
		URL:             url,
		Method:          http.MethodPost,
		MultipartFields: map[string]MultipartField{"image": {Type: "file", Value: fp}},
	}
}

// Python decides what every status means, so a raw upload returns the
// host's answer as is and never re-sends it because of its status, even a
// status the retry config lists (only 429 and 503 are retried; see
// raw_upload_retry_test.go).
func TestRawUploadReturnsTheHostAnswerForEveryStatusWithoutRetrying(t *testing.T) {
	fp := writeUploadFile(t, 2048)
	for _, status := range []int{http.StatusOK, http.StatusForbidden, http.StatusBadGateway} {
		var hits int32
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			atomic.AddInt32(&hits, 1)
			_, _ = io.Copy(io.Discard, r.Body)
			w.WriteHeader(status)
			_, _ = w.Write([]byte(`{"error":"host says no"}`))
		}))
		job := rawJob(fp, rawRequest(server.URL+"/upload", fp), fastRetries())
		result, err := ExecuteRawUpload(context.Background(), server.Client(), fp, job)
		server.Close()
		if err != nil {
			t.Fatalf("status %d: raw upload failed: %v", status, err)
		}
		if result.StatusCode != status || result.Body != `{"error":"host says no"}` {
			t.Fatalf("status %d: result = %+v", status, result)
		}
		if result.FinalURL != server.URL+"/upload" {
			t.Fatalf("final url = %q", result.FinalURL)
		}
		if got := atomic.LoadInt32(&hits); got != 1 {
			t.Fatalf("status %d: host received %d uploads, want 1", status, got)
		}
	}
}

func TestRawUploadFinalURLFollowsRedirects(t *testing.T) {
	fp := writeUploadFile(t, 128)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		if r.URL.Path == "/upload" {
			http.Redirect(w, r, "/done?id=7", http.StatusSeeOther)
			return
		}
		_, _ = w.Write([]byte("done page"))
	}))
	defer server.Close()

	result, err := ExecuteRawUpload(context.Background(), server.Client(), fp, rawJob(fp, rawRequest(server.URL+"/upload", fp), fastRetries()))
	if err != nil {
		t.Fatalf("raw upload: %v", err)
	}
	if result.FinalURL != server.URL+"/done?id=7" || result.Body != "done page" {
		t.Fatalf("result = %+v", result)
	}
}

// Values are literal in raw mode: brace text is never substituted. Text
// fields go first in name order, then the file.
func TestRawUploadSendsLiteralValuesWithTheFileLast(t *testing.T) {
	fp := writeUploadFile(t, 256)
	type part struct{ name, value string }
	var parts []part
	var header string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		header = r.Header.Get("X-Token")
		_, params, _ := mime.ParseMediaType(r.Header.Get("Content-Type"))
		reader := multipart.NewReader(r.Body, params["boundary"])
		for {
			p, err := reader.NextPart()
			if err != nil {
				break
			}
			data, _ := io.ReadAll(p)
			value := string(data)
			if p.FileName() != "" {
				value = "file:" + p.FileName()
			}
			parts = append(parts, part{p.FormName(), value})
		}
		_, _ = w.Write([]byte("ok"))
	}))
	defer server.Close()

	request := &RawUploadRequest{
		URL:     server.URL + "/upload",
		Headers: map[string]string{"X-Token": "{token}"},
		MultipartFields: map[string]MultipartField{
			"z_title": {Type: "text", Value: "Holiday {2024} {filename}"},
			"a_id":    {Type: "text", Value: "{upload_id}"},
			"image":   {Type: "file", Value: fp},
		},
		FormFields: map[string]string{"m_extra": "{file_size}"},
	}
	job := rawJob(fp, request, fastRetries())
	job.Creds = map[string]string{"token": "secret-token"}
	if _, err := ExecuteRawUpload(context.Background(), server.Client(), fp, job); err != nil {
		t.Fatalf("raw upload: %v", err)
	}
	want := []part{{"a_id", "{upload_id}"}, {"m_extra", "{file_size}"}, {"z_title", "Holiday {2024} {filename}"}, {"image", "file:photo.jpg"}}
	if len(parts) != len(want) {
		t.Fatalf("parts = %+v, want %+v", parts, want)
	}
	for i := range want {
		if parts[i] != want[i] {
			t.Fatalf("part %d = %+v, want %+v (all %+v)", i, parts[i], want[i], parts)
		}
	}
	if header != "{token}" {
		t.Fatalf("header = %q, want the literal value", header)
	}
}

func TestRawUploadResponseIsCappedAt2MiB(t *testing.T) {
	fp := writeUploadFile(t, 64)
	for _, tc := range []struct {
		size int
		ok   bool
	}{{MaxRawResponseBytes, true}, {MaxRawResponseBytes + 1, false}} {
		var hits int32
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			atomic.AddInt32(&hits, 1)
			_, _ = io.Copy(io.Discard, r.Body)
			_, _ = w.Write([]byte(strings.Repeat("x", tc.size)))
		}))
		result, err := ExecuteRawUpload(context.Background(), server.Client(), fp, rawJob(fp, rawRequest(server.URL, fp), fastRetries()))
		server.Close()
		if tc.ok {
			if err != nil || len(result.Body) != tc.size {
				t.Fatalf("%d-byte answer: err=%v len=%d", tc.size, err, len(result.Body))
			}
			continue
		}
		if err == nil || !strings.Contains(err.Error(), "upload response too large") {
			t.Fatalf("%d-byte answer: err = %v, want upload response too large", tc.size, err)
		}
		if got := atomic.LoadInt32(&hits); got != 1 {
			t.Fatalf("an oversized answer was retried: %d uploads", got)
		}
	}
}

func TestRawUploadWithoutARequestOrWithABadOneFails(t *testing.T) {
	fp := writeUploadFile(t, 64)
	other := writeUploadFile(t, 64)
	job := rawJob(fp, rawRequest("http://unused.test/upload", fp), fastRetries())
	if _, err := ExecuteRawUpload(context.Background(), http.DefaultClient, other, job); err == nil || err.Error() != "missing upload request" {
		t.Fatalf("err = %v, want missing upload request", err)
	}

	cases := map[string]*RawUploadRequest{
		"no url":           {MultipartFields: map[string]MultipartField{"image": {Type: "file", Value: fp}}},
		"no file field":    {URL: "http://unused.test", MultipartFields: map[string]MultipartField{"a": {Type: "text", Value: "x"}}},
		"two file fields":  {URL: "http://unused.test", MultipartFields: map[string]MultipartField{"a": {Type: "file", Value: fp}, "b": {Type: "file", Value: fp}}},
		"another file":     {URL: "http://unused.test", MultipartFields: map[string]MultipartField{"a": {Type: "file", Value: other}}},
		"unsupported type": {URL: "http://unused.test", MultipartFields: map[string]MultipartField{"a": {Type: "file", Value: fp}, "t": {Type: "dynamic", Value: "token"}}},
	}
	for name, request := range cases {
		_, err := ExecuteRawUpload(context.Background(), http.DefaultClient, fp, rawJob(fp, request, fastRetries()))
		if err == nil || !strings.Contains(err.Error(), "invalid upload request") {
			t.Fatalf("%s: err = %v, want invalid upload request", name, err)
		}
	}
}

// The upload-attempt protections apply to raw uploads: a body that reached
// the host whose answer was lost is never sent again.
func TestRawUploadIsNotRepeatedWhenResponseIsLost(t *testing.T) {
	fp := writeUploadFile(t, 4096)
	var stored int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		if atomic.AddInt32(&stored, 1) == 1 {
			if conn, _, err := w.(http.Hijacker).Hijack(); err == nil {
				_ = conn.Close()
			}
			return
		}
		_, _ = w.Write([]byte("stored again"))
	}))
	defer server.Close()

	_, err := ExecuteRawUpload(context.Background(), server.Client(), fp, rawJob(fp, rawRequest(server.URL, fp), fastRetries()))
	if err == nil || !strings.Contains(err.Error(), "no response from host after upload; check the host before retrying") {
		t.Fatalf("err = %v, want the no-response message", err)
	}
	if got := atomic.LoadInt32(&stored); got != 1 {
		t.Fatalf("host stored the image %d times, want 1", got)
	}
	if !UploadBodySent(err) {
		t.Fatal("a lost answer after the whole body was sent must report the body as sent")
	}
}

// Python matches result pages by upload order and must know which failed
// uploads may still have been stored by the host.
func TestRawUploadFailureSaysWhetherTheBodyReachedTheHost(t *testing.T) {
	setUploadLimits(t, 200*time.Millisecond, time.Second)
	fp := writeUploadFile(t, 64*1024)
	_, err := ExecuteRawUpload(context.Background(), &http.Client{Transport: stalledTransport{}}, fp,
		rawJob(fp, rawRequest("http://stall.test", fp), &RetryConfig{}))
	if err == nil || UploadBodySent(err) {
		t.Fatalf("stalled before the body was sent: err=%v body sent=%v", err, UploadBodySent(err))
	}

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		_, _ = w.Write([]byte(strings.Repeat("x", MaxRawResponseBytes+1)))
	}))
	defer server.Close()
	_, err = ExecuteRawUpload(context.Background(), server.Client(), fp, rawJob(fp, rawRequest(server.URL, fp), fastRetries()))
	if err == nil || !UploadBodySent(err) {
		t.Fatalf("an oversized answer means the host got the body: err=%v", err)
	}
	if UploadBodySent(nil) || UploadBodySent(errMissingUploadRequest) {
		t.Fatal("errors before any attempt must not report a sent body")
	}
}

func TestStalledRawUploadFails(t *testing.T) {
	setUploadLimits(t, 200*time.Millisecond, time.Second)
	fp := writeUploadFile(t, 64*1024)
	client := &http.Client{Transport: stalledTransport{}}
	start := time.Now()
	_, err := ExecuteRawUpload(context.Background(), client, fp, rawJob(fp, rawRequest("http://stall.test", fp), &RetryConfig{}))
	if err == nil || !strings.Contains(err.Error(), "upload stalled") {
		t.Fatalf("err = %v, want upload stalled", err)
	}
	if elapsed := time.Since(start); elapsed > 5*time.Second {
		t.Fatalf("stall detected after %v", elapsed)
	}
}

func TestRawUploadResponseWaitIsBounded(t *testing.T) {
	setUploadLimits(t, time.Second, 200*time.Millisecond)
	fp := writeUploadFile(t, 4096)
	release := make(chan struct{})
	var stored int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		atomic.AddInt32(&stored, 1)
		select {
		case <-release:
		case <-r.Context().Done():
		}
	}))
	defer server.Close()
	defer close(release)

	_, err := ExecuteRawUpload(context.Background(), server.Client(), fp, rawJob(fp, rawRequest(server.URL, fp), fastRetries()))
	if err == nil || !strings.Contains(err.Error(), "no response from host") {
		t.Fatalf("err = %v, want the no-response message", err)
	}
	if got := atomic.LoadInt32(&stored); got != 1 {
		t.Fatalf("host received the upload %d times, want 1", got)
	}
}

func TestRawUploadHonoursCancellationAndDeadline(t *testing.T) {
	fp := writeUploadFile(t, 4096)
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		select {
		case <-release:
		case <-r.Context().Done():
		}
	}))
	defer server.Close()
	defer close(release)

	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
	defer cancel()
	start := time.Now()
	_, err := ExecuteRawUpload(ctx, server.Client(), fp, rawJob(fp, rawRequest(server.URL, fp), fastRetries()))
	if err == nil {
		t.Fatal("raw upload outlived its deadline")
	}
	if elapsed := time.Since(start); elapsed > 5*time.Second {
		t.Fatalf("deadline honoured after %v", elapsed)
	}
}

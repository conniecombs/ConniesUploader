// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package core

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	"github.com/PuerkitoBio/goquery"
)

// DoRequest performs a generic HTTP request with the given client.
// Callers are responsible for setting service-specific headers (e.g. Referer).
func DoRequest(ctx context.Context, client *http.Client, method, urlStr string, body io.Reader, contentType string) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, method, urlStr, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", DefaultUserAgent)
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	return client.Do(req)
}

// ExecuteHttpUpload runs a generic multipart upload described by job.HttpSpec.
func ExecuteHttpUpload(ctx context.Context, client *http.Client, fp string, job *JobRequest) (string, string, error) {
	spec := job.HttpSpec
	if spec == nil {
		return "", "", fmt.Errorf("no http_spec")
	}
	if job.Service != "" {
		if err := WaitForRateLimit(ctx, job.Service); err != nil {
			return "", "", err
		}
	}

	extractedValues := make(map[string]string)
	var sessionClient *http.Client
	if spec.PreRequest != nil {
		var err error
		extractedValues, sessionClient, err = ExecutePreRequest(ctx, client, spec.PreRequest)
		if err != nil {
			return "", "", err
		}
	}

	pr, pw := io.Pipe()
	writer := multipart.NewWriter(pw)
	go func() {
		defer pw.Close()
		defer writer.Close()
		for fieldName, field := range spec.MultipartFields {
			switch field.Type {
			case "file":
				part, _ := writer.CreateFormFile(fieldName, filepath.Base(fp))
				f, err := os.Open(fp) // #nosec G304
				if err != nil {
					pw.CloseWithError(err)
					return
				}
				defer f.Close()
				fi, err := f.Stat()
				if err != nil {
					pw.CloseWithError(err)
					return
				}
				pw2 := NewProgressWriter(part, fi.Size(), fp)
				if _, err := io.Copy(pw2, f); err != nil {
					pw.CloseWithError(err)
					return
				}
			case "text":
				_ = writer.WriteField(fieldName, field.Value)
			case "dynamic":
				if val, ok := extractedValues[field.Value]; ok {
					_ = writer.WriteField(fieldName, val)
				}
			}
		}
	}()

	req, _ := http.NewRequestWithContext(ctx, spec.Method, spec.URL, pr)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("User-Agent", DefaultUserAgent)
	for k, v := range spec.Headers {
		req.Header.Set(k, v)
	}

	useClient := client
	if sessionClient != nil {
		useClient = sessionClient
	}
	resp, err := useClient.Do(req)
	if err != nil {
		return "", "", err
	}
	defer resp.Body.Close()
	return ParseHttpResponse(resp, &spec.ResponseParser, fp)
}

// ExecutePreRequest handles optional pre-request (login/session) steps.
func ExecutePreRequest(ctx context.Context, client *http.Client, spec *PreRequestSpec) (map[string]string, *http.Client, error) {
	preClient := client
	if spec.UseCookies {
		jar, _ := cookiejar.New(nil)
		preClient = &http.Client{
			Timeout: PreRequestTimeout,
			Jar:     jar,
			Transport: &http.Transport{
				MaxIdleConnsPerHost:   10,
				ResponseHeaderTimeout: PreRequestHeaderTimeout,
			},
		}
	}

	var reqBody io.Reader
	contentType := ""
	if len(spec.FormFields) > 0 {
		v := url.Values{}
		for k, val := range spec.FormFields {
			v.Set(k, val)
		}
		reqBody = strings.NewReader(v.Encode())
		contentType = "application/x-www-form-urlencoded"
	}

	req, _ := http.NewRequestWithContext(ctx, spec.Method, spec.URL, reqBody)
	req.Header.Set("User-Agent", DefaultUserAgent)
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	for k, v := range spec.Headers {
		req.Header.Set(k, v)
	}

	resp, err := preClient.Do(req)
	if err != nil {
		return nil, nil, err
	}
	defer resp.Body.Close()
	bodyBytes, _ := io.ReadAll(resp.Body)

	extracted := make(map[string]string)
	switch spec.ResponseType {
	case "json":
		var data map[string]interface{}
		_ = json.Unmarshal(bodyBytes, &data)
		for k, path := range spec.ExtractFields {
			extracted[k] = GetJSONValue(data, path)
		}
	case "html":
		doc, _ := goquery.NewDocumentFromReader(bytes.NewReader(bodyBytes))
		for k, sel := range spec.ExtractFields {
			val := doc.Find(sel).AttrOr("value", "")
			if val == "" {
				val = doc.Find(sel).Text()
			}
			extracted[k] = strings.TrimSpace(val)
		}
	}
	return extracted, preClient, nil
}

// ParseHttpResponse parses an upload response using the given parser spec.
func ParseHttpResponse(resp *http.Response, parser *ResponseParserSpec, _ string) (string, string, error) {
	bodyBytes, _ := io.ReadAll(resp.Body)
	if parser.Type != "json" {
		return "", "", fmt.Errorf("unsupported parser type: %s", parser.Type)
	}
	var data map[string]interface{}
	if err := json.Unmarshal(bodyBytes, &data); err != nil {
		return "", "", err
	}
	if parser.StatusPath != "" && GetJSONValue(data, parser.StatusPath) != parser.SuccessValue {
		return "", "", fmt.Errorf("upload failed: status check did not match")
	}
	return GetJSONValue(data, parser.URLPath), GetJSONValue(data, parser.ThumbPath), nil
}

// GetJSONValue extracts a value from a nested map using dot-notation path.
func GetJSONValue(data map[string]interface{}, path string) string {
	current := interface{}(data)
	for _, part := range strings.Split(path, ".") {
		m, ok := current.(map[string]interface{})
		if !ok {
			return ""
		}
		current = m[part]
	}
	switch v := current.(type) {
	case string:
		return v
	case float64:
		return fmt.Sprintf("%.0f", v)
	case bool:
		if v {
			return "true"
		}
		return "false"
	}
	return ""
}

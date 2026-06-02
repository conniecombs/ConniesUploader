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
	log "github.com/sirupsen/logrus"
)

// DoRequest performs a generic HTTP request with the given client.
// Callers are responsible for setting service-specific headers (e.g. Referer).
func DoRequest(ctx context.Context, client *http.Client, method, urlStr string, body io.Reader, contentType string) (*http.Response, error) {
	var bodyBytes []byte
	if body != nil {
		var err error
		bodyBytes, err = io.ReadAll(body)
		if err != nil {
			return nil, fmt.Errorf("failed to read request body: %w", err)
		}
	}

	retryConfig := GetDefaultRetryConfig()
	logger := log.WithFields(log.Fields{
		"method": method,
		"url":    urlStr,
	})

	return RetryWithBackoff(ctx, retryConfig, func() (*http.Response, int, error) {
		var reqBody io.Reader
		if bodyBytes != nil {
			reqBody = bytes.NewReader(bodyBytes)
		}

		req, err := http.NewRequestWithContext(ctx, method, urlStr, reqBody)
		if err != nil {
			return nil, 0, err
		}
		req.Header.Set("User-Agent", DefaultUserAgent)
		if contentType != "" {
			req.Header.Set("Content-Type", contentType)
		}

		resp, err := client.Do(req)
		if err != nil {
			return nil, 0, err
		}

		for _, code := range retryConfig.RetryableHTTPCodes {
			if resp.StatusCode == code {
				resp.Body.Close()
				return nil, resp.StatusCode, fmt.Errorf("HTTP %d", resp.StatusCode)
			}
		}

		return resp, resp.StatusCode, nil
	}, logger)
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

	retryConfig := GetDefaultRetryConfig()
	logger := log.WithFields(log.Fields{
		"action": "upload",
		"file":   filepath.Base(fp),
		"url":    spec.URL,
	})

	type uploadResult struct {
		URL   string
		Thumb string
	}

	res, err := RetryWithBackoff(ctx, retryConfig, func() (uploadResult, int, error) {
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

		req, err := http.NewRequestWithContext(ctx, spec.Method, spec.URL, pr)
		if err != nil {
			return uploadResult{}, 0, err
		}
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
			return uploadResult{}, 0, err
		}
		defer resp.Body.Close()

		for _, code := range retryConfig.RetryableHTTPCodes {
			if resp.StatusCode == code {
				return uploadResult{}, resp.StatusCode, fmt.Errorf("HTTP %d", resp.StatusCode)
			}
		}

		urlStr, thumbStr, err := ParseHttpResponse(resp, &spec.ResponseParser, fp)
		return uploadResult{URL: urlStr, Thumb: thumbStr}, resp.StatusCode, err
	}, logger)

	if err != nil {
		return "", "", err
	}
	return res.URL, res.Thumb, nil
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

	retryConfig := GetDefaultRetryConfig()
	logger := log.WithFields(log.Fields{
		"action": "pre_request",
		"url":    spec.URL,
	})

	type preReqResult struct {
		Extracted map[string]string
		Client    *http.Client
	}

	res, err := RetryWithBackoff(ctx, retryConfig, func() (preReqResult, int, error) {
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

		req, err := http.NewRequestWithContext(ctx, spec.Method, spec.URL, reqBody)
		if err != nil {
			return preReqResult{}, 0, err
		}
		req.Header.Set("User-Agent", DefaultUserAgent)
		if contentType != "" {
			req.Header.Set("Content-Type", contentType)
		}
		for k, v := range spec.Headers {
			req.Header.Set(k, v)
		}

		resp, err := preClient.Do(req)
		if err != nil {
			return preReqResult{}, 0, err
		}
		defer resp.Body.Close()

		for _, code := range retryConfig.RetryableHTTPCodes {
			if resp.StatusCode == code {
				return preReqResult{}, resp.StatusCode, fmt.Errorf("HTTP %d", resp.StatusCode)
			}
		}

		bodyBytes, err := io.ReadAll(resp.Body)
		if err != nil {
			return preReqResult{}, resp.StatusCode, err
		}

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
		return preReqResult{Extracted: extracted, Client: preClient}, resp.StatusCode, nil
	}, logger)

	if err != nil {
		return nil, nil, err
	}
	return res.Extracted, res.Client, nil
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

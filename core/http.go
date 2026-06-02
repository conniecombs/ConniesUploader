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
	"regexp"
	"strconv"
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
				_ = resp.Body.Close()
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
	for k, v := range job.Creds {
		extractedValues[k] = v
	}
	for k, v := range job.Config {
		extractedValues[k] = v
	}

	var sessionClient *http.Client
	if spec.PreRequest != nil {
		var err error
		preValues, preClient, err := ExecutePreRequest(ctx, client, spec.PreRequest)
		if err != nil {
			return "", "", err
		}
		for k, v := range preValues {
			extractedValues[k] = v
		}
		sessionClient = preClient
	}

	uploadURL := resolveUploadURL(spec.URL, extractedValues)

	retryConfig := GetDefaultRetryConfig()
	logger := log.WithFields(log.Fields{
		"action": "upload",
		"file":   filepath.Base(fp),
		"url":    uploadURL,
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
					fi, err := f.Stat()
					if err != nil {
						_ = f.Close()
						pw.CloseWithError(err)
						return
					}
					pw2 := NewProgressWriter(part, fi.Size(), fp)
					_, err = io.Copy(pw2, f)
					_ = f.Close()
					if err != nil {
						pw.CloseWithError(err)
						return
					}
				case "text":
					_ = writer.WriteField(fieldName, substituteValues(field.Value, extractedValues))
				case "dynamic":
					if val, ok := extractedValues[field.Value]; ok {
						_ = writer.WriteField(fieldName, val)
					} else {
						_ = writer.WriteField(fieldName, substituteValues(field.Value, extractedValues))
					}
				}
			}
		}()

		method := spec.Method
		if method == "" {
			method = http.MethodPost
		}

		req, err := http.NewRequestWithContext(ctx, method, uploadURL, pr)
		if err != nil {
			return uploadResult{}, 0, err
		}
		req.Header.Set("Content-Type", writer.FormDataContentType())
		req.Header.Set("User-Agent", GetUserAgent(job.Config))
		for k, v := range spec.Headers {
			req.Header.Set(k, substituteValues(v, extractedValues))
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
	values := make(map[string]string)
	if spec == nil {
		return values, client, nil
	}
	return executePreRequest(ctx, preRequestClient(client, spec.UseCookies), spec, values)
}

func executePreRequest(
	ctx context.Context,
	preClient *http.Client,
	spec *PreRequestSpec,
	values map[string]string,
) (map[string]string, *http.Client, error) {
	if spec == nil {
		return values, preClient, nil
	}
	if preClient == nil {
		preClient = &http.Client{Timeout: PreRequestTimeout}
	}
	if spec.UseCookies && preClient.Jar == nil {
		preClient = preRequestClient(preClient, true)
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
				v.Set(k, substituteValues(val, values))
			}
			reqBody = strings.NewReader(v.Encode())
			contentType = "application/x-www-form-urlencoded"
		}

		method := spec.Method
		if method == "" {
			method = http.MethodGet
		}

		req, err := http.NewRequestWithContext(ctx, method, substituteValues(spec.URL, values), reqBody)
		if err != nil {
			return preReqResult{}, 0, err
		}
		req.Header.Set("User-Agent", DefaultUserAgent)
		if contentType != "" {
			req.Header.Set("Content-Type", contentType)
		}
		for k, v := range spec.Headers {
			req.Header.Set(k, substituteValues(v, values))
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

		extracted, err := extractFields(bodyBytes, spec.ResponseType, spec.ExtractFields)
		if err != nil {
			return preReqResult{}, resp.StatusCode, err
		}
		return preReqResult{Extracted: extracted, Client: preClient}, resp.StatusCode, nil
	}, logger)

	if err != nil {
		return nil, nil, err
	}

	for k, v := range res.Extracted {
		values[k] = v
	}
	if spec.FollowUpRequest != nil {
		return executePreRequest(ctx, res.Client, spec.FollowUpRequest, values)
	}
	return values, res.Client, nil
}

// ParseHttpResponse parses an upload response using the given parser spec.
func ParseHttpResponse(resp *http.Response, parser *ResponseParserSpec, fp string) (string, string, error) {
	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", "", err
	}

	switch strings.ToLower(parser.Type) {
	case "", "json":
		var data map[string]interface{}
		if err := json.Unmarshal(bodyBytes, &data); err != nil {
			return "", "", err
		}
		if parser.StatusPath != "" && GetJSONValue(data, parser.StatusPath) != parser.SuccessValue {
			return "", "", fmt.Errorf("upload failed: status check did not match")
		}

		urlStr := GetJSONValue(data, parser.URLPath)
		if urlStr == "" && parser.URLTemplate != "" {
			urlStr = applyResponseTemplate(parser.URLTemplate, data, fp)
		}
		thumbStr := GetJSONValue(data, parser.ThumbPath)
		if thumbStr == "" && parser.ThumbTemplate != "" {
			thumbStr = applyResponseTemplate(parser.ThumbTemplate, data, fp)
		}
		return urlStr, thumbStr, nil
	case "html":
		urlStr, err := extractHTMLField(bodyBytes, parser.URLPath)
		if err != nil {
			return "", "", err
		}
		thumbStr, err := extractHTMLField(bodyBytes, parser.ThumbPath)
		if err != nil {
			return "", "", err
		}
		if urlStr == "" && parser.URLTemplate != "" {
			urlStr = applyResponseTemplate(parser.URLTemplate, nil, fp)
		}
		if thumbStr == "" && parser.ThumbTemplate != "" {
			thumbStr = applyResponseTemplate(parser.ThumbTemplate, nil, fp)
		}
		return urlStr, thumbStr, nil
	default:
		return "", "", fmt.Errorf("unsupported parser type: %s", parser.Type)
	}
}

// GetJSONValue extracts a scalar value from nested JSON using dot-notation.
// Numeric path parts index arrays, e.g. files.0.sourceUrl.
func GetJSONValue(data map[string]interface{}, path string) string {
	if path == "" {
		return ""
	}
	current := interface{}(data)
	for _, part := range strings.Split(path, ".") {
		switch node := current.(type) {
		case map[string]interface{}:
			current = node[part]
		case []interface{}:
			index, err := strconv.Atoi(part)
			if err != nil || index < 0 || index >= len(node) {
				return ""
			}
			current = node[index]
		default:
			return ""
		}
	}
	return scalarToString(current)
}

func scalarToString(current interface{}) string {
	switch v := current.(type) {
	case string:
		return v
	case float64:
		return fmt.Sprintf("%.0f", v)
	case int:
		return fmt.Sprintf("%d", v)
	case int64:
		return fmt.Sprintf("%d", v)
	case bool:
		if v {
			return "true"
		}
		return "false"
	}
	return ""
}

func preRequestClient(base *http.Client, useCookies bool) *http.Client {
	if !useCookies {
		return base
	}
	jar, _ := cookiejar.New(nil)
	return &http.Client{
		Timeout: PreRequestTimeout,
		Jar:     jar,
		Transport: &http.Transport{
			MaxIdleConnsPerHost:   10,
			ResponseHeaderTimeout: PreRequestHeaderTimeout,
		},
	}
}

func extractFields(body []byte, responseType string, fields map[string]string) (map[string]string, error) {
	extracted := make(map[string]string)
	switch strings.ToLower(responseType) {
	case "json":
		var data map[string]interface{}
		if err := json.Unmarshal(body, &data); err != nil {
			return nil, err
		}
		for k, path := range fields {
			extracted[k] = GetJSONValue(data, path)
		}
	case "", "html":
		for k, selector := range fields {
			val, err := extractHTMLField(body, selector)
			if err != nil {
				return nil, err
			}
			extracted[k] = val
		}
	default:
		return nil, fmt.Errorf("unsupported pre-request response type: %s", responseType)
	}
	return extracted, nil
}

func extractHTMLField(body []byte, selector string) (string, error) {
	if selector == "" {
		return "", nil
	}
	if strings.HasPrefix(selector, "regex:") {
		pattern := strings.TrimPrefix(selector, "regex:")
		re, err := regexp.Compile(pattern)
		if err != nil {
			return "", err
		}
		matches := re.FindStringSubmatch(string(body))
		if len(matches) > 1 {
			return strings.TrimSpace(matches[1]), nil
		}
		if len(matches) == 1 {
			return strings.TrimSpace(matches[0]), nil
		}
		return "", nil
	}

	doc, err := goquery.NewDocumentFromReader(bytes.NewReader(body))
	if err != nil {
		return "", err
	}
	return selectionValue(doc.Find(selector).First()), nil
}

func selectionValue(sel *goquery.Selection) string {
	if sel == nil || sel.Length() == 0 {
		return ""
	}
	for _, attr := range []string{"value", "content", "action", "href", "src", "data-url"} {
		if val, ok := sel.Attr(attr); ok && strings.TrimSpace(val) != "" {
			return strings.TrimSpace(val)
		}
	}
	return strings.TrimSpace(sel.Text())
}

func substituteValues(input string, values map[string]string) string {
	if input == "" || len(values) == 0 {
		return input
	}
	result := input
	for key, val := range values {
		result = strings.ReplaceAll(result, "{"+key+"}", val)
	}
	return result
}

func resolveUploadURL(specURL string, values map[string]string) string {
	resolved := substituteValues(specURL, values)
	endpoint := strings.TrimSpace(values["endpoint"])
	if endpoint == "" || strings.Contains(specURL, "{endpoint}") {
		return resolved
	}

	upload, err := url.Parse(resolved)
	if err != nil {
		return resolved
	}
	endpointURL, err := url.Parse(endpoint)
	if err != nil {
		return resolved
	}
	finalURL := upload.ResolveReference(endpointURL)
	if finalURL.RawQuery == "" {
		finalURL.RawQuery = upload.RawQuery
	}
	return finalURL.String()
}

var templateTokenPattern = regexp.MustCompile(`\{([^{}]+)\}`)

func applyResponseTemplate(template string, data map[string]interface{}, fp string) string {
	base := filepath.Base(fp)
	ext := strings.TrimPrefix(filepath.Ext(base), ".")
	stem := strings.TrimSuffix(base, filepath.Ext(base))

	return templateTokenPattern.ReplaceAllStringFunc(template, func(token string) string {
		key := strings.Trim(token, "{}")
		switch key {
		case "filename":
			return base
		case "basename":
			return stem
		case "ext", "extension":
			return ext
		case "dot_ext":
			if ext == "" {
				return ""
			}
			return "." + ext
		}
		if data == nil {
			return ""
		}
		if val := GetJSONValue(data, key); val != "" {
			return val
		}
		return findJSONScalar(data, key)
	})
}

func findJSONScalar(value interface{}, key string) string {
	switch node := value.(type) {
	case map[string]interface{}:
		if val, ok := node[key]; ok {
			return scalarToString(val)
		}
		for _, child := range node {
			if val := findJSONScalar(child, key); val != "" {
				return val
			}
		}
	case []interface{}:
		for _, child := range node {
			if val := findJSONScalar(child, key); val != "" {
				return val
			}
		}
	}
	return ""
}

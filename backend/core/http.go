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
	"time"

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

type HTTPUploadResult struct {
	URL   string
	Thumb string
	Data  map[string]string
}

// ExecuteHttpUpload runs a generic multipart upload described by job.HttpSpec.
func ExecuteHttpUpload(ctx context.Context, client *http.Client, fp string, job *JobRequest) (string, string, error) {
	result, err := ExecuteHttpUploadWithData(ctx, client, fp, job)
	if err != nil {
		return "", "", err
	}
	return result.URL, result.Thumb, nil
}

// ExecuteHttpUploadWithData runs a generic upload and preserves optional result metadata.
func ExecuteHttpUploadWithData(ctx context.Context, client *http.Client, fp string, job *JobRequest) (HTTPUploadResult, error) {
	spec := job.HttpSpec
	if spec == nil {
		return HTTPUploadResult{}, fmt.Errorf("no http_spec")
	}
	if job.Service != "" {
		emitUploadStatus(job, fp, "Waiting")
		emitUploadLog(job, fp, fmt.Sprintf("Waiting for rate limit: %s", filepath.Base(fp)))
		if err := WaitForRateLimit(ctx, job.Service); err != nil {
			return HTTPUploadResult{}, err
		}
		emitUploadLog(job, fp, fmt.Sprintf("Rate limit cleared: %s", filepath.Base(fp)))
	}
	emitUploadStatus(job, fp, "Preparing")

	extractedValues := make(map[string]string)
	for k, v := range job.Creds {
		extractedValues[k] = v
	}
	for k, v := range job.Config {
		extractedValues[k] = v
	}
	extractedValues["filename"] = filepath.Base(fp)

	retryConfig := retryConfigForJob(job)

	var sessionClient *http.Client
	if spec.PreRequest != nil {
		var err error
		emitUploadStatus(job, fp, "Preparing")
		emitUploadLog(job, fp, fmt.Sprintf("Preparing session data: %s", filepath.Base(fp)))
		preValues, preClient, err := executePreRequestWithRetryConfig(ctx, client, spec.PreRequest, retryConfig)
		if err != nil {
			return HTTPUploadResult{}, err
		}
		emitUploadLog(job, fp, fmt.Sprintf("Session data ready: %s", filepath.Base(fp)))
		for k, v := range preValues {
			extractedValues[k] = v
		}
		sessionClient = preClient
	}

	uploadURL := resolveUploadURL(spec.URL, extractedValues)

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
		defer pr.Close()
		writer := multipart.NewWriter(pw)
		go func() {
			closeErr := func() error {
				for fieldName, field := range spec.MultipartFields {
					switch field.Type {
					case "file":
						part, err := writer.CreateFormFile(fieldName, filepath.Base(fp))
						if err != nil {
							return err
						}
						f, err := os.Open(fp) // #nosec G304
						if err != nil {
							return err
						}
						fi, err := f.Stat()
						if err != nil {
							_ = f.Close()
							return err
						}
						pw2 := NewProgressWriter(part, fi.Size(), fp, job.ID)
						_, copyErr := io.Copy(pw2, f)
						_ = f.Close()
						if copyErr != nil {
							return copyErr
						}
					case "text":
						if err := writer.WriteField(fieldName, substituteValues(field.Value, extractedValues)); err != nil {
							return err
						}
					case "dynamic":
						value := substituteValues(field.Value, extractedValues)
						if val, ok := extractedValues[field.Value]; ok {
							value = val
						}
						if err := writer.WriteField(fieldName, value); err != nil {
							return err
						}
					}
				}
				return writer.Close()
			}()
			if closeErr != nil {
				_ = pw.CloseWithError(closeErr)
				return
			}
			_ = pw.Close()
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
		emitUploadStatus(job, fp, "Uploading")
		emitUploadLog(job, fp, fmt.Sprintf("HTTP upload request started: %s", filepath.Base(fp)))
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

		urlStr, thumbStr, err := ParseHttpResponseWithClient(ctx, useClient, resp, &spec.ResponseParser, fp)
		return uploadResult{URL: urlStr, Thumb: thumbStr}, resp.StatusCode, err
	}, logger)

	if err != nil {
		return HTTPUploadResult{}, err
	}
	if job != nil && job.ResolveSpec != nil && strings.TrimSpace(res.URL) != "" && strings.TrimSpace(res.Thumb) == "" {
		resolveSpec := *job.ResolveSpec
		if strings.TrimSpace(resolveSpec.ResultURL) == "" {
			resolveSpec.ResultURL = res.URL
		} else {
			resolveValues := make(map[string]string, len(extractedValues)+3)
			for key, value := range extractedValues {
				resolveValues[key] = value
			}
			resolveValues["url"] = res.URL
			resolveValues["thumb"] = res.Thumb
			resolveValues["filename"] = filepath.Base(fp)
			resolveSpec.ResultURL = substituteValues(resolveSpec.ResultURL, resolveValues)
		}

		resolveClient := client
		if sessionClient != nil {
			resolveClient = sessionClient
		}
		fileNames := map[string]string{fp: filepath.Base(fp)}
		resolved, resolveData, resolveErr := ExecuteBatchResolveWithData(ctx, resolveClient, &resolveSpec, []string{fp}, fileNames)
		if resolveErr != nil {
			return HTTPUploadResult{}, fmt.Errorf("resolve upload result: %w", resolveErr)
		}
		if pair, ok := resolved[fp]; ok && strings.TrimSpace(pair[0]) != "" && strings.TrimSpace(pair[1]) != "" {
			return HTTPUploadResult{URL: pair[0], Thumb: pair[1], Data: resolveData}, nil
		}
		return HTTPUploadResult{}, fmt.Errorf("resolve upload result: result page did not contain image and thumbnail links")
	}
	return HTTPUploadResult{URL: res.URL, Thumb: res.Thumb}, nil
}

func emitUploadStatus(job *JobRequest, fp string, status string) {
	event := OutputEvent{Type: "status", FilePath: fp, Status: status}
	if job != nil {
		event.ID = job.ID
	}
	SendJSON(event)
}

func emitUploadLog(job *JobRequest, fp string, msg string) {
	event := OutputEvent{Type: "log", FilePath: fp, Msg: msg}
	if job != nil {
		event.ID = job.ID
	}
	SendJSON(event)
}

func retryConfigForJob(job *JobRequest) *RetryConfig {
	if job != nil && job.RetryConfig != nil {
		return job.RetryConfig
	}
	return GetDefaultRetryConfig()
}

// ExecutePreRequest handles optional pre-request (login/session) steps.
func ExecutePreRequest(ctx context.Context, client *http.Client, spec *PreRequestSpec) (map[string]string, *http.Client, error) {
	return executePreRequestWithRetryConfig(ctx, client, spec, GetDefaultRetryConfig())
}

func executePreRequestWithRetryConfig(
	ctx context.Context,
	client *http.Client,
	spec *PreRequestSpec,
	retryConfig *RetryConfig,
) (map[string]string, *http.Client, error) {
	values := make(map[string]string)
	if spec == nil {
		return values, client, nil
	}
	if retryConfig == nil {
		retryConfig = GetDefaultRetryConfig()
	}
	return executePreRequest(ctx, preRequestClient(client, spec.UseCookies), spec, values, retryConfig)
}

func executePreRequest(
	ctx context.Context,
	preClient *http.Client,
	spec *PreRequestSpec,
	values map[string]string,
	retryConfig *RetryConfig,
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
		return executePreRequest(ctx, res.Client, spec.FollowUpRequest, values, retryConfig)
	}
	return values, res.Client, nil
}

// ParseHttpResponse parses an upload response using the given parser spec.
func ParseHttpResponse(resp *http.Response, parser *ResponseParserSpec, fp string) (string, string, error) {
	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", "", err
	}
	return parseHttpResponseBody(bodyBytes, parser, fp)
}

func ParseHttpResponseWithClient(ctx context.Context, client *http.Client, resp *http.Response, parser *ResponseParserSpec, fp string) (string, string, error) {
	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", "", err
	}
	if parser != nil && parser.FollowUpRequest != nil {
		bodyBytes, err = executeResponseFollowUp(ctx, client, resp, bodyBytes, parser.FollowUpRequest)
		if err != nil {
			return "", "", err
		}
	}
	return parseHttpResponseBody(bodyBytes, parser, fp)
}

func parseHttpResponseBody(bodyBytes []byte, parser *ResponseParserSpec, fp string) (string, string, error) {
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

func executeResponseFollowUp(ctx context.Context, client *http.Client, resp *http.Response, bodyBytes []byte, spec *ResponseFollowUpSpec) ([]byte, error) {
	if spec == nil {
		return bodyBytes, nil
	}
	if client == nil {
		client = http.DefaultClient
	}

	values := make(map[string]string)
	if len(spec.ExtractFields) > 0 {
		extracted, err := extractFields(bodyBytes, spec.ResponseType, spec.ExtractFields)
		if err != nil {
			return nil, fmt.Errorf("response follow-up field extraction failed: %w", err)
		}
		for key, value := range extracted {
			values[key] = value
		}
	}

	method := spec.Method
	if method == "" {
		method = http.MethodPost
	}

	targetURL := spec.URL
	if targetURL == "" && resp != nil && resp.Request != nil && resp.Request.URL != nil {
		targetURL = resp.Request.URL.String()
	}
	if resp != nil && resp.Request != nil && resp.Request.URL != nil {
		base := resp.Request.URL
		if parsed, err := url.Parse(targetURL); err == nil {
			targetURL = base.ResolveReference(parsed).String()
		}
	}
	targetURL = substituteValues(targetURL, values)

	form := url.Values{}
	for key, value := range spec.FormFields {
		form.Set(key, substituteValues(value, values))
	}
	if len(form) == 0 {
		for key, value := range values {
			form.Set(key, value)
		}
	}

	req, err := http.NewRequestWithContext(ctx, method, targetURL, strings.NewReader(form.Encode()))
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", DefaultUserAgent)
	if len(form) > 0 {
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	}
	for key, value := range spec.Headers {
		req.Header.Set(key, substituteValues(value, values))
	}

	nextResp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer nextResp.Body.Close()

	nextBody, err := io.ReadAll(nextResp.Body)
	if err != nil {
		return nil, err
	}
	if nextResp.StatusCode < 200 || nextResp.StatusCode >= 300 {
		return nil, fmt.Errorf("response follow-up HTTP %d: %s", nextResp.StatusCode, strings.TrimSpace(string(nextBody)))
	}
	return nextBody, nil
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
		return strconv.FormatFloat(v, 'f', -1, 64)
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
		key := strings.TrimSpace(strings.Trim(token, "{}"))
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

// ExecuteGenericRequest executes a standalone HTTP request described by a
// GenericHttpRequestSpec. It handles pre-requests, value extraction, and
// success checking. Returns the extracted values map.
func ExecuteGenericRequest(ctx context.Context, client *http.Client, spec *GenericHttpRequestSpec, job *JobRequest) (map[string]string, error) {
	if spec == nil {
		return nil, fmt.Errorf("no generic_spec")
	}

	extractedValues := make(map[string]string)
	if job != nil {
		for k, v := range job.Creds {
			extractedValues[k] = v
		}
		for k, v := range job.Config {
			extractedValues[k] = v
		}
	}

	retryConfig := retryConfigForJob(job)

	// Execute pre-request chain if specified.
	var sessionClient *http.Client
	if spec.PreRequest != nil {
		preValues, preClient, err := executePreRequestWithRetryConfig(ctx, client, spec.PreRequest, retryConfig)
		if err != nil {
			return nil, fmt.Errorf("pre-request failed: %w", err)
		}
		for k, v := range preValues {
			extractedValues[k] = v
		}
		sessionClient = preClient
	}

	useClient := client
	if sessionClient != nil {
		useClient = sessionClient
	} else if spec.UseCookies && client.Jar == nil {
		useClient = preRequestClient(client, true)
	}

	// Build the main request.
	resolvedURL := substituteValues(spec.URL, extractedValues)
	method := spec.Method
	if method == "" {
		method = http.MethodGet
	}

	var reqBody io.Reader
	contentType := ""
	if len(spec.FormFields) > 0 {
		v := url.Values{}
		for k, val := range spec.FormFields {
			v.Set(k, substituteValues(val, extractedValues))
		}
		reqBody = strings.NewReader(v.Encode())
		contentType = "application/x-www-form-urlencoded"
	}

	logger := log.WithFields(log.Fields{
		"action": "generic_request",
		"url":    resolvedURL,
		"method": method,
	})

	type reqResult struct {
		Extracted map[string]string
	}

	res, err := RetryWithBackoff(ctx, retryConfig, func() (reqResult, int, error) {
		var body io.Reader
		if reqBody != nil {
			// Re-create body for retries.
			v := url.Values{}
			for k, val := range spec.FormFields {
				v.Set(k, substituteValues(val, extractedValues))
			}
			body = strings.NewReader(v.Encode())
		}

		req, err := http.NewRequestWithContext(ctx, method, resolvedURL, body)
		if err != nil {
			return reqResult{}, 0, err
		}
		req.Header.Set("User-Agent", DefaultUserAgent)
		if contentType != "" {
			req.Header.Set("Content-Type", contentType)
		}
		for k, v := range spec.Headers {
			req.Header.Set(k, substituteValues(v, extractedValues))
		}

		resp, err := useClient.Do(req)
		if err != nil {
			return reqResult{}, 0, err
		}
		defer resp.Body.Close()

		for _, code := range retryConfig.RetryableHTTPCodes {
			if resp.StatusCode == code {
				return reqResult{}, resp.StatusCode, fmt.Errorf("HTTP %d", resp.StatusCode)
			}
		}

		if resp.StatusCode < 200 || resp.StatusCode >= 300 {
			rawBody, _ := io.ReadAll(resp.Body)
			return reqResult{}, resp.StatusCode, fmt.Errorf("HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(rawBody)))
		}

		bodyBytes, err := io.ReadAll(resp.Body)
		if err != nil {
			return reqResult{}, resp.StatusCode, err
		}

		extracted := make(map[string]string)
		if len(spec.ExtractFields) > 0 {
			extracted, err = extractFields(bodyBytes, spec.ResponseType, spec.ExtractFields)
			if err != nil {
				return reqResult{}, resp.StatusCode, fmt.Errorf("field extraction failed: %w", err)
			}
		}

		// Store raw body for success checking.
		extracted["__response_body__"] = string(bodyBytes)
		extracted["__status_code__"] = fmt.Sprintf("%d", resp.StatusCode)
		if resp.Request != nil && resp.Request.URL != nil {
			extracted["__final_url__"] = resp.Request.URL.String()
		}

		return reqResult{Extracted: extracted}, resp.StatusCode, nil
	}, logger)

	if err != nil {
		return nil, err
	}

	// Merge extracted values.
	for k, v := range res.Extracted {
		extractedValues[k] = v
	}

	// Check success condition if specified.
	if spec.SuccessCheck != nil {
		if err := checkSuccess(spec.SuccessCheck, extractedValues); err != nil {
			return extractedValues, err
		}
	}

	return extractedValues, nil
}

// checkSuccess verifies that extracted values meet the success criteria.
func checkSuccess(check *SuccessCheck, values map[string]string) error {
	if check == nil {
		return nil
	}

	if len(check.Any) > 0 {
		failures := make([]string, 0, len(check.Any))
		for i := range check.Any {
			if err := checkSuccess(&check.Any[i], values); err == nil {
				return nil
			} else {
				failures = append(failures, err.Error())
			}
		}
		return fmt.Errorf(
			"success check failed: none of %d conditions matched (%s)",
			len(check.Any),
			strings.Join(failures, "; "),
		)
	}

	var fieldValue string
	if check.Field == "__response_body__" {
		fieldValue = values["__response_body__"]
	} else {
		fieldValue = values[check.Field]
	}

	switch check.Type {
	case "contains":
		if !strings.Contains(fieldValue, check.Match) {
			return fmt.Errorf("success check failed: field %q does not contain %q", check.Field, check.Match)
		}
	case "equals":
		if fieldValue != check.Match {
			return fmt.Errorf("success check failed: field %q is %q, expected %q", check.Field, fieldValue, check.Match)
		}
	case "not_empty":
		if strings.TrimSpace(fieldValue) == "" {
			return fmt.Errorf("success check failed: field %q is empty", check.Field)
		}
	case "regex":
		re, err := regexp.Compile(check.Match)
		if err != nil {
			return fmt.Errorf("success check regex error: %w", err)
		}
		if !re.MatchString(fieldValue) {
			return fmt.Errorf("success check failed: field %q does not match pattern %q", check.Field, check.Match)
		}
	default:
		// No check type specified or unknown, treat as pass.
	}

	return nil
}

// ExecuteBatchResolve polls a result page for per-file image links.
// Returns a map from file path to (url, thumb).
func ExecuteBatchResolve(
	ctx context.Context,
	client *http.Client,
	spec *BatchResolveSpec,
	files []string,
	fileNames map[string]string,
) (map[string][2]string, error) {
	results, _, err := ExecuteBatchResolveWithData(ctx, client, spec, files, fileNames)
	return results, err
}

func ExecuteBatchResolveWithData(
	ctx context.Context,
	client *http.Client,
	spec *BatchResolveSpec,
	files []string,
	fileNames map[string]string,
) (map[string][2]string, map[string]string, error) {
	if spec == nil {
		return nil, nil, fmt.Errorf("no resolve_spec")
	}

	results := make(map[string][2]string, len(files))
	metadata := make(map[string]string)
	pending := make(map[string]struct{}, len(files))
	for _, fp := range files {
		pending[fp] = struct{}{}
	}

	linkRe, err := regexp.Compile(spec.LinkExtractor)
	if err != nil {
		return nil, nil, fmt.Errorf("invalid link_extractor regex: %w", err)
	}

	var thumbRe *regexp.Regexp
	if spec.ThumbExtractor != "" {
		thumbRe, err = regexp.Compile(spec.ThumbExtractor)
		if err != nil {
			return nil, nil, fmt.Errorf("invalid thumb_extractor regex: %w", err)
		}
	}

	delays := spec.PollDelaysMs
	if len(delays) == 0 {
		delays = []int{500, 1000, 2000, 3000, 5000, 5000, 5000, 5000, 5000, 5000}
	}
	attempts := 1 + len(delays)

	var lastErr error
	for attempt := 0; attempt < attempts && len(pending) > 0; attempt++ {
		if attempt > 0 {
			delay := time.Duration(delays[attempt-1]) * time.Millisecond
			select {
			case <-time.After(delay):
			case <-ctx.Done():
				return results, metadata, ctx.Err()
			}
		}

		req, err := http.NewRequestWithContext(ctx, "GET", spec.ResultURL, nil)
		if err != nil {
			lastErr = err
			continue
		}
		req.Header.Set("User-Agent", DefaultUserAgent)

		resp, err := client.Do(req)
		if err != nil {
			lastErr = err
			continue
		}

		bodyBytes, readErr := io.ReadAll(resp.Body)
		_ = resp.Body.Close()
		if readErr != nil {
			lastErr = readErr
			continue
		}

		if resp.StatusCode < 200 || resp.StatusCode >= 300 {
			lastErr = fmt.Errorf("result page HTTP %d", resp.StatusCode)
			continue
		}

		bodyStr := string(bodyBytes)

		if spec.GalleryExtractor != "" && strings.TrimSpace(metadata["gallery_url"]) == "" {
			galleryURL, extractErr := extractHTMLField(bodyBytes, spec.GalleryExtractor)
			if extractErr != nil {
				return results, metadata, fmt.Errorf("gallery_extractor: %w", extractErr)
			}
			if strings.TrimSpace(galleryURL) != "" {
				metadata["gallery_url"] = strings.TrimSpace(galleryURL)
			}
		}

		// Extract all links from the page.
		matches := linkRe.FindAllStringSubmatch(bodyStr, -1)
		for _, match := range matches {
			imageURL := namedGroup(linkRe, match, "image_url")
			thumbURL := namedGroup(linkRe, match, "thumb_url")
			matchName := namedGroup(linkRe, match, "filename")

			if imageURL == "" {
				continue
			}

			// Match to pending files.
			for fp := range pending {
				expected := fileNames[fp]
				if expected == "" {
					expected = filepath.Base(fp)
				}
				if batchFileMatches(matchName, expected, imageURL, spec.FileMatchMode) {
					results[fp] = [2]string{imageURL, thumbURL}
					delete(pending, fp)
					break
				}
			}
		}

		// Try thumb extractor separately if provided.
		if thumbRe != nil {
			thumbMatches := thumbRe.FindAllStringSubmatch(bodyStr, -1)
			for _, tm := range thumbMatches {
				thumbURL := namedGroup(thumbRe, tm, "thumb_url")
				matchName := namedGroup(thumbRe, tm, "filename")
				if thumbURL == "" {
					continue
				}
				for fp, result := range results {
					if result[1] != "" {
						continue
					}
					expected := fileNames[fp]
					if expected == "" {
						expected = filepath.Base(fp)
					}
					if batchFileMatches(matchName, expected, thumbURL, spec.FileMatchMode) {
						results[fp] = [2]string{result[0], thumbURL}
						break
					}
				}
			}
		}

		if len(pending) > 0 {
			lastErr = fmt.Errorf("result page missing %d link(s)", len(pending))
		}
	}

	if len(pending) > 0 && lastErr != nil {
		return results, metadata, lastErr
	}
	return results, metadata, nil
}

func namedGroup(re *regexp.Regexp, match []string, name string) string {
	for i, groupName := range re.SubexpNames() {
		if groupName == name && i < len(match) {
			return strings.TrimSpace(match[i])
		}
	}
	// Fall back to positional groups.
	if name == "image_url" && len(match) > 1 {
		return strings.TrimSpace(match[1])
	}
	if name == "thumb_url" && len(match) > 2 {
		return strings.TrimSpace(match[2])
	}
	return ""
}

func batchFileMatches(matchName, expected, urlStr, mode string) bool {
	expectedLower := normalizeBatchFileName(expected)
	if expectedLower == "" {
		return false
	}

	switch mode {
	case "first", "single":
		return true
	case "contains":
		if matchName != "" && strings.Contains(normalizeBatchFileName(matchName), expectedLower) {
			return true
		}
		if urlStr != "" && strings.Contains(normalizeBatchFileName(urlStr), expectedLower) {
			return true
		}
		return false
	default: // "filename"
		if matchName != "" {
			normalized := normalizeBatchFileName(matchName)
			if normalized == expectedLower || strings.HasSuffix(normalized, "_"+expectedLower) || strings.Contains(normalized, expectedLower) {
				return true
			}
		}
		if urlStr != "" {
			parsedURL, err := url.Parse(urlStr)
			if err == nil {
				baseName := normalizeBatchFileName(filepath.Base(parsedURL.Path))
				if baseName == expectedLower || strings.Contains(baseName, expectedLower) {
					return true
				}
			}
		}
		return false
	}
}

func normalizeBatchFileName(value string) string {
	cleaned := strings.ToLower(strings.TrimSpace(value))
	if cleaned == "" {
		return ""
	}
	if parsedURL, err := url.Parse(cleaned); err == nil && parsedURL.Path != "" {
		cleaned = filepath.Base(parsedURL.Path)
	}
	if unescaped, err := url.QueryUnescape(cleaned); err == nil {
		cleaned = unescaped
	}
	cleaned = strings.TrimSuffix(cleaned, ".html")
	return strings.TrimSpace(cleaned)
}

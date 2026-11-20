// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"bytes"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"unicode"

	"github.com/PuerkitoBio/goquery"
)

// maxResponseSnippetRunes bounds how much of a host's response an error quotes.
const maxResponseSnippetRunes = 200

// hostMessageKeys are the JSON fields hosts commonly use to explain a failure,
// most specific first. Only string values count.
var hostMessageKeys = []string{
	"error.message",
	"error",
	"message",
	"msg",
	"error_message",
	"errors.0.message",
	"errors.0",
	"data.error.message",
	"data.error",
	"data.message",
	"detail",
	"reason",
	"status_txt",
}

// uploadFailure describes a host's refusal of an upload: the reason, the HTTP
// status, and the host's own message, or else a short sanitized snippet of the
// response. Secret values are redacted from the quoted text.
func uploadFailure(reason string, status int, body []byte, secrets []string) error {
	detail := truncateRunes(redactSecrets(hostMessageText(body), secrets), maxResponseSnippetRunes)
	if detail == "" {
		return fmt.Errorf("%s (HTTP %d)", reason, status)
	}
	return fmt.Errorf("%s (HTTP %d): %s", reason, status, detail)
}

// hostMessage returns the host's error text from a JSON body, or a short plain
// text snippet of any other body.
func hostMessage(body []byte) string {
	return truncateRunes(hostMessageText(body), maxResponseSnippetRunes)
}

// hostMessageText is hostMessage without the length limit, so secrets can be
// redacted before the text is cut.
func hostMessageText(body []byte) string {
	trimmed := bytes.TrimSpace(body)
	if len(trimmed) == 0 {
		return ""
	}
	var data map[string]interface{}
	if trimmed[0] == '{' && json.Unmarshal(trimmed, &data) == nil {
		for _, path := range hostMessageKeys {
			if msg := jsonStringAt(data, path); msg != "" {
				return collapseText(msg)
			}
		}
		return collapseText(string(trimmed))
	}
	if bytes.ContainsRune(trimmed, '<') {
		if text := htmlVisibleText(trimmed); text != "" {
			return text
		}
	}
	return collapseText(string(trimmed))
}

// jsonStringAt is GetJSONValue restricted to non-empty string values.
func jsonStringAt(data map[string]interface{}, path string) string {
	current := interface{}(data)
	for _, part := range strings.Split(path, ".") {
		switch node := current.(type) {
		case map[string]interface{}:
			current = node[part]
		case []interface{}:
			index := -1
			if _, err := fmt.Sscanf(part, "%d", &index); err != nil || index < 0 || index >= len(node) {
				return ""
			}
			current = node[index]
		default:
			return ""
		}
	}
	text, _ := current.(string)
	return strings.TrimSpace(text)
}

// htmlVisibleText returns the visible text of an HTML document: the body's
// text without scripts or styles, else the page title.
func htmlVisibleText(body []byte) string {
	doc, err := goquery.NewDocumentFromReader(bytes.NewReader(body))
	if err != nil {
		return ""
	}
	var parts []string
	var walk func(*goquery.Selection)
	walk = func(sel *goquery.Selection) {
		sel.Contents().Each(func(_ int, child *goquery.Selection) {
			switch goquery.NodeName(child) {
			case "#text":
				parts = append(parts, child.Text())
			case "script", "style", "noscript", "template", "head", "#comment":
			default:
				walk(child)
			}
		})
	}
	walk(doc.Find("body"))
	if text := collapseText(strings.Join(parts, " ")); text != "" {
		return text
	}
	return collapseText(doc.Find("title").First().Text())
}

func collapseText(text string) string {
	text = strings.Map(func(r rune) rune {
		if unicode.IsControl(r) {
			return ' '
		}
		return r
	}, text)
	return strings.Join(strings.Fields(text), " ")
}

func truncateRunes(text string, limit int) string {
	runes := []rune(text)
	if len(runes) <= limit {
		return text
	}
	return strings.TrimSpace(string(runes[:limit])) + "…"
}

// uploadSecrets lists the job's credential and session values that must not be
// quoted back in an error message.
func uploadSecrets(job *JobRequest) []string {
	if job == nil {
		return nil
	}
	var secrets []string
	for _, values := range []map[string]string{job.Creds, job.SessionValues} {
		for _, value := range values {
			if len(strings.TrimSpace(value)) >= 4 {
				secrets = append(secrets, value)
			}
		}
	}
	// Longest first, so a secret that contains another is redacted whole.
	sort.Slice(secrets, func(i, j int) bool { return len(secrets[i]) > len(secrets[j]) })
	return secrets
}

func redactSecrets(text string, secrets []string) string {
	for _, secret := range secrets {
		text = strings.ReplaceAll(text, secret, "[redacted]")
	}
	return text
}

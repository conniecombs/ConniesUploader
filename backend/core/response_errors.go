// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"bytes"
	"encoding/json"
	"fmt"
	"html"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf16"
	"unicode/utf8"

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
	detail := uploadFailureDetail(body, secrets)
	if detail == "" {
		return fmt.Errorf("%s (HTTP %d)", reason, status)
	}
	return fmt.Errorf("%s (HTTP %d): %s", reason, status, detail)
}

// uploadFailureDetail is the part of a response an upload failure quotes: the
// host's own message, else a short sanitized snippet, with secrets redacted.
func uploadFailureDetail(body []byte, secrets []string) string {
	return truncateRunes(redactSecrets(hostMessageText(body), secrets), maxResponseSnippetRunes)
}

// followUpFailure turns a failed response follow-up of an upload into an
// upload failure. It stays an *HTTPStatusError with the follow-up's status,
// but quotes only what uploadFailure would, never the whole page.
func followUpFailure(statusErr *HTTPStatusError, secrets []string) error {
	return &HTTPStatusError{
		Context:    statusErr.Context,
		StatusCode: statusErr.StatusCode,
		Body:       uploadFailureDetail([]byte(statusErr.Body), secrets),
	}
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
// quoted back in an error message. loginValues are the values a pre_request
// that ran for this file alone extracted (a single-file or once_per_file job);
// a shared session's values are already in job.SessionValues.
func uploadSecrets(job *JobRequest, loginValues map[string]string) []string {
	if job == nil {
		return nil
	}
	seen := make(map[string]bool)
	var secrets []string
	for _, values := range []map[string]string{job.Creds, job.SessionValues, loginValues} {
		for _, value := range values {
			// Shorter values would mangle the text; length counts characters.
			if utf8.RuneCountInString(strings.TrimSpace(value)) >= 4 && !seen[value] {
				seen[value] = true
				secrets = append(secrets, value)
			}
		}
	}
	// Longest first, so a secret that contains another is redacted whole.
	sort.Slice(secrets, func(i, j int) bool {
		li, lj := utf8.RuneCountInString(secrets[i]), utf8.RuneCountInString(secrets[j])
		if li != lj {
			return li > lj
		}
		return secrets[i] < secrets[j]
	})
	return secrets
}

const redacted = "[redacted]"

// redactSecrets replaces each secret in text with "[redacted]", as given or
// escaped: a host may echo a credential back URL-encoded ("P%40ss",
// "my+pass"), JSON-escaped ("P@ss\/w0rd", "\u00e9") or with HTML character
// references ("&eacute;", "&#233;") in text no parser decoded. secrets are
// longest first (uploadSecrets). frontend/modules/upload_results.py's
// redact_secrets does the same.
func redactSecrets(text string, secrets []string) string {
	for _, secret := range secrets {
		text = strings.ReplaceAll(text, secret, redacted)
	}
	for _, form := range escapeForms {
		text = redactEscaped(text, secrets, form.pattern, form.decode)
	}
	return text
}

// escapeForms are the escaped forms a credential may take: a token pattern
// and its decoder (false: the token stands for nothing and stays as
// written). Keep in step with _ESCAPE_FORMS in upload_results.py.
var escapeForms = []struct {
	pattern *regexp.Regexp
	decode  func(token string) (string, bool)
}{
	{regexp.MustCompile(`%[0-9A-Fa-f]{2}|\+`), decodePercentEscape},
	{
		regexp.MustCompile(`\\u[dD][89abAB][0-9a-fA-F]{2}\\u[dD][c-fC-F][0-9a-fA-F]{2}` +
			`|\\u[0-9a-fA-F]{4}|\\["\\/bfnrt]`),
		decodeJSONEscape,
	},
	{
		regexp.MustCompile(`&#[0-9]{1,8};|&#[xX][0-9a-fA-F]{1,8};|&[A-Za-z][A-Za-z0-9]{0,31};`),
		decodeHTMLEscape,
	},
}

func decodePercentEscape(token string) (string, bool) {
	if token == "+" {
		return " ", true
	}
	value, err := strconv.ParseUint(token[1:], 16, 8)
	return string([]byte{byte(value)}), err == nil
}

var jsonShortEscapes = map[byte]string{
	'"': `"`, '\\': `\`, '/': "/", 'b': "\b", 'f': "\f", 'n': "\n", 'r': "\r", 't': "\t",
}

func decodeJSONEscape(token string) (string, bool) {
	if !strings.HasPrefix(token, `\u`) {
		return jsonShortEscapes[token[1]], true
	}
	unit, _ := strconv.ParseUint(token[2:6], 16, 32)
	if len(token) == 12 { // a surrogate pair
		low, _ := strconv.ParseUint(token[8:12], 16, 32)
		return string(utf16.DecodeRune(rune(unit), rune(low))), true
	}
	if utf16.IsSurrogate(rune(unit)) {
		return "", false // a lone surrogate stands for no character
	}
	return string(rune(unit)), true
}

func decodeHTMLEscape(token string) (string, bool) {
	if strings.HasPrefix(token, "&#") {
		digits := token[2 : len(token)-1]
		base := 10
		if digits[0] == 'x' || digits[0] == 'X' {
			digits, base = digits[1:], 16
		}
		code, err := strconv.ParseInt(digits, base, 64)
		if err != nil || code <= 0 || code > unicode.MaxRune || (code >= 0xD800 && code <= 0xDFFF) {
			return "", false
		}
		return string(rune(code)), true
	}
	value := html.UnescapeString(token)
	// A name that is no entity, or only starts with one, keeps its ";".
	return value, !strings.HasSuffix(value, ";")
}

// redactEscaped redacts each secret where text spells it with pattern's
// escapes. The text is decoded into bytes, escape by escape; a secret
// matches where the decoded bytes equal it and it starts and ends on whole
// escapes (or characters). Longest secrets first, left to right, never
// overlapping.
func redactEscaped(text string, secrets []string, pattern *regexp.Regexp, decode func(string) (string, bool)) string {
	type segment struct {
		start, end, textStart, textEnd int
		escape                         bool
	}
	var segments []segment
	var decoded []byte
	add := func(textStart, textEnd int, value string, escape bool) {
		segments = append(segments, segment{len(decoded), len(decoded) + len(value), textStart, textEnd, escape})
		decoded = append(decoded, value...)
	}
	cursor := 0
	for _, loc := range pattern.FindAllStringIndex(text, -1) {
		value, ok := decode(text[loc[0]:loc[1]])
		if !ok {
			continue
		}
		if loc[0] > cursor {
			add(cursor, loc[0], text[cursor:loc[0]], false)
		}
		add(loc[0], loc[1], value, true)
		cursor = loc[1]
	}
	if len(segments) == 0 {
		return text
	}
	if cursor < len(text) {
		add(cursor, len(text), text[cursor:], false)
	}

	// textOffset is where a decoded offset is in text; false inside an
	// escape or a character.
	textOffset := func(offset int) (int, bool) {
		k := sort.Search(len(segments), func(i int) bool { return segments[i].start > offset }) - 1
		seg := segments[k]
		switch {
		case offset == seg.start:
			return seg.textStart, true
		case offset == seg.end:
			return seg.textEnd, true
		case seg.escape || !utf8.RuneStart(decoded[offset]):
			return 0, false
		}
		return seg.textStart + offset - seg.start, true
	}

	type span struct{ start, end int }
	var spans []span
	overlaps := func(start, end int) bool {
		for _, taken := range spans {
			if start < taken.end && taken.start < end {
				return true
			}
		}
		return false
	}
	for _, secret := range secrets {
		for position := 0; position <= len(decoded); {
			found := bytes.Index(decoded[position:], []byte(secret))
			if found < 0 {
				break
			}
			found += position
			start, okStart := textOffset(found)
			end, okEnd := textOffset(found + len(secret))
			if okStart && okEnd && !overlaps(start, end) {
				spans = append(spans, span{start, end})
				position = found + len(secret)
			} else {
				position = found + 1
			}
		}
	}
	if len(spans) == 0 {
		return text
	}
	sort.Slice(spans, func(i, j int) bool { return spans[i].start < spans[j].start })
	var out strings.Builder
	last := 0
	for _, taken := range spans {
		out.WriteString(text[last:taken.start])
		out.WriteString(redacted)
		last = taken.end
	}
	out.WriteString(text[last:])
	return out.String()
}

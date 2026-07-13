// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package core

import (
	"crypto/rand"
	"fmt"
	"strings"
	"time"
)

const Charset = "abcdefghijklmnopqrstuvwxyz0123456789"

func RandomString(n int) string {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		return fmt.Sprintf("%d", time.Now().UnixNano())
	}
	for i := range b {
		b[i] = Charset[int(b[i])%len(Charset)]
	}
	return string(b)
}

var quoteEscaper = strings.NewReplacer("\\", "\\\\", `"`, "\\\"")

func QuoteEscape(s string) string { return quoteEscaper.Replace(s) }

// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"sync"
)

// SwappableJar is a cookie jar whose contents can be discarded atomically
// while other goroutines keep using the same *http.Client.
type SwappableJar struct {
	mu    sync.RWMutex
	inner http.CookieJar
}

// NewSwappableJar returns an empty jar backed by net/http/cookiejar.
func NewSwappableJar() *SwappableJar {
	jar := &SwappableJar{}
	jar.Reset()
	return jar
}

// Reset replaces the stored cookies with an empty jar.
func (j *SwappableJar) Reset() {
	inner, err := cookiejar.New(nil)
	if err != nil {
		inner = nil
	}
	j.mu.Lock()
	j.inner = inner
	j.mu.Unlock()
}

// SetCookies implements http.CookieJar.
func (j *SwappableJar) SetCookies(u *url.URL, cookies []*http.Cookie) {
	j.mu.RLock()
	inner := j.inner
	j.mu.RUnlock()
	if inner != nil {
		inner.SetCookies(u, cookies)
	}
}

// Cookies implements http.CookieJar.
func (j *SwappableJar) Cookies(u *url.URL) []*http.Cookie {
	j.mu.RLock()
	inner := j.inner
	j.mu.RUnlock()
	if inner == nil {
		return nil
	}
	return inner.Cookies(u)
}

// ResetCookieJar drops every cookie of client when its jar is swappable.
// Plain jars are left untouched because they cannot be cleared in place.
func ResetCookieJar(client *http.Client) {
	if client == nil {
		return
	}
	if jar, ok := client.Jar.(*SwappableJar); ok {
		jar.Reset()
	}
}

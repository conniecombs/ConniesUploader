// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"testing"
)

func TestSwappableJarResetDropsCookies(t *testing.T) {
	jar := NewSwappableJar()
	u, _ := url.Parse("https://example.test/")
	jar.SetCookies(u, []*http.Cookie{{Name: "session", Value: "abc"}})
	if len(jar.Cookies(u)) != 1 {
		t.Fatalf("cookie was not stored")
	}
	jar.Reset()
	if got := jar.Cookies(u); len(got) != 0 {
		t.Fatalf("cookies after Reset = %v, want none", got)
	}
}

func TestResetCookieJarIgnoresPlainJars(t *testing.T) {
	plain, _ := cookiejar.New(nil)
	u, _ := url.Parse("https://example.test/")
	plain.SetCookies(u, []*http.Cookie{{Name: "keep", Value: "1"}})
	client := &http.Client{Jar: plain}
	ResetCookieJar(client)
	if len(client.Jar.Cookies(u)) != 1 {
		t.Fatalf("plain jar must be left untouched")
	}
	swappable := NewSwappableJar()
	swappable.SetCookies(u, []*http.Cookie{{Name: "drop", Value: "1"}})
	ResetCookieJar(&http.Client{Jar: swappable})
	if len(swappable.Cookies(u)) != 0 {
		t.Fatalf("swappable jar was not reset")
	}
}

// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"testing"
)

func mustURL(t *testing.T, raw string) *url.URL {
	t.Helper()
	u, err := url.Parse(raw)
	if err != nil {
		t.Fatalf("parse %q: %v", raw, err)
	}
	return u
}

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

func TestResetSiteCookiesIgnoresPlainJars(t *testing.T) {
	plain, _ := cookiejar.New(nil)
	u, _ := url.Parse("https://example.test/")
	plain.SetCookies(u, []*http.Cookie{{Name: "keep", Value: "1"}})
	client := &http.Client{Jar: plain}
	ResetSiteCookies(client, u.String())
	if len(client.Jar.Cookies(u)) != 1 {
		t.Fatalf("plain jar must be left untouched")
	}
	swappable := NewSwappableJar()
	swappable.SetCookies(u, []*http.Cookie{{Name: "drop", Value: "1"}})
	ResetSiteCookies(&http.Client{Jar: swappable}, u.String())
	if len(swappable.Cookies(u)) != 0 {
		t.Fatalf("swappable jar was not reset")
	}
}

// A forum login resets only the forum's cookies; an image host's session in
// the same jar survives.
func TestResetSiteCookiesKeepsOtherSites(t *testing.T) {
	jar := NewSwappableJar()
	imageHost := mustURL(t, "https://img.example.com/")
	forum := mustURL(t, "https://forum.example.org/login.php")
	forumWWW := mustURL(t, "https://www.forum.example.org/")
	jar.SetCookies(imageHost, []*http.Cookie{{Name: "xfss", Value: "image-session"}})
	jar.SetCookies(forum, []*http.Cookie{{Name: "bb_session", Value: "old"}})
	jar.SetCookies(forumWWW, []*http.Cookie{{Name: "bb_www", Value: "old", Domain: "forum.example.org"}})

	ResetSiteCookies(&http.Client{Jar: jar}, "https://www.forum.example.org/login.php?do=login")

	if got := jar.Cookies(forum); len(got) != 0 {
		t.Fatalf("forum cookies after reset = %v, want none", got)
	}
	if got := jar.Cookies(forumWWW); len(got) != 0 {
		t.Fatalf("forum subdomain cookies after reset = %v, want none", got)
	}
	got := jar.Cookies(imageHost)
	if len(got) != 1 || got[0].Value != "image-session" {
		t.Fatalf("image host cookies after forum reset = %v, want the session kept", got)
	}
}

func TestSwappableJarKeepsDomainCookiesWithinTheirSite(t *testing.T) {
	jar := NewSwappableJar()
	jar.SetCookies(mustURL(t, "https://www.example.com/"),
		[]*http.Cookie{{Name: "shared", Value: "1", Domain: "example.com"}})
	if got := jar.Cookies(mustURL(t, "https://api.example.com/")); len(got) != 1 {
		t.Fatalf("domain cookie not sent to a sibling subdomain: %v", got)
	}
	if got := jar.Cookies(mustURL(t, "https://example.net/")); len(got) != 0 {
		t.Fatalf("cookie leaked to another site: %v", got)
	}
}

func TestSiteKeyGroupsByRegistrableDomain(t *testing.T) {
	cases := map[string]string{
		"https://www.forum.example.org/x": "example.org",
		"https://a.b.example.co.uk/":      "example.co.uk",
		"http://127.0.0.1:8080/":          "127.0.0.1",
		"http://[::1]:8080/":              "::1",
		"http://localhost:9000/":          "localhost",
		"https://Example.COM./":           "example.com",
	}
	for raw, want := range cases {
		if got := siteKey(mustURL(t, raw)); got != want {
			t.Errorf("siteKey(%q) = %q, want %q", raw, got, want)
		}
	}
}

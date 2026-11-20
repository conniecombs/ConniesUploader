// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"net"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"strings"
	"sync"

	"golang.org/x/net/publicsuffix"
)

// SwappableJar is the shared cookie jar. It keeps each site's cookies in a
// separate jar, keyed by registrable domain, so one site's cookies can be
// discarded (ResetSite) while other goroutines keep using the same
// *http.Client and every other site keeps its session.
type SwappableJar struct {
	mu    sync.RWMutex
	sites map[string]http.CookieJar
}

// NewSwappableJar returns an empty jar backed by net/http/cookiejar.
func NewSwappableJar() *SwappableJar {
	return &SwappableJar{sites: map[string]http.CookieJar{}}
}

// siteKey returns the registrable domain (eTLD+1) of u's host, so a site's
// subdomains share one jar. IP addresses and hosts without a registrable
// domain (such as localhost) are their own site.
func siteKey(u *url.URL) string {
	host := strings.TrimSuffix(strings.ToLower(u.Hostname()), ".")
	if host == "" || net.ParseIP(host) != nil {
		return host
	}
	if site, err := publicsuffix.EffectiveTLDPlusOne(host); err == nil {
		return site
	}
	return host
}

func (j *SwappableJar) siteJar(u *url.URL, create bool) http.CookieJar {
	key := siteKey(u)
	j.mu.RLock()
	jar := j.sites[key]
	j.mu.RUnlock()
	if jar != nil || !create {
		return jar
	}
	j.mu.Lock()
	defer j.mu.Unlock()
	if jar = j.sites[key]; jar == nil {
		created, err := cookiejar.New(nil)
		if err != nil {
			return nil
		}
		jar = created
		j.sites[key] = jar
	}
	return jar
}

// Reset discards the cookies of every site.
func (j *SwappableJar) Reset() {
	j.mu.Lock()
	j.sites = map[string]http.CookieJar{}
	j.mu.Unlock()
}

// ResetSite discards the cookies of u's site and leaves other sites alone.
func (j *SwappableJar) ResetSite(u *url.URL) {
	j.mu.Lock()
	delete(j.sites, siteKey(u))
	j.mu.Unlock()
}

// SetCookies implements http.CookieJar.
func (j *SwappableJar) SetCookies(u *url.URL, cookies []*http.Cookie) {
	if jar := j.siteJar(u, true); jar != nil {
		jar.SetCookies(u, cookies)
	}
}

// Cookies implements http.CookieJar.
func (j *SwappableJar) Cookies(u *url.URL) []*http.Cookie {
	if jar := j.siteJar(u, false); jar != nil {
		return jar.Cookies(u)
	}
	return nil
}

// ResetSiteCookies drops the cookies client holds for rawURL's site when its
// jar is swappable. Plain jars, and URLs without a host, are left untouched.
func ResetSiteCookies(client *http.Client, rawURL string) {
	if client == nil {
		return
	}
	jar, ok := client.Jar.(*SwappableJar)
	if !ok {
		return
	}
	u, err := url.Parse(rawURL)
	if err != nil || u.Hostname() == "" {
		return
	}
	jar.ResetSite(u)
}

// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"net/http"
	"net/http/cookiejar"
	"sync"
	"time"

	log "github.com/sirupsen/logrus"

	"github.com/conniecombs/GolangVersion/core"
	"github.com/conniecombs/GolangVersion/services"
	"github.com/conniecombs/GolangVersion/services/imagebam"
	"github.com/conniecombs/GolangVersion/services/imx"
	"github.com/conniecombs/GolangVersion/services/pixhost"
	"github.com/conniecombs/GolangVersion/services/turbo"
	"github.com/conniecombs/GolangVersion/services/vipergirls"
	"github.com/conniecombs/GolangVersion/services/vipr"
)

var (
	client       *http.Client
	registry     *services.Registry
	runtimeMutex sync.Mutex
)

func newHTTPClient() *http.Client {
	jar, err := cookiejar.New(nil)
	if err != nil {
		log.WithError(err).Warn("failed to initialize cookie jar; continuing without persistent cookies")
	}

	return &http.Client{
		Timeout: core.ClientTimeout,
		Jar:     jar,
		Transport: &http.Transport{
			MaxIdleConns:          100,
			MaxIdleConnsPerHost:   10,
			MaxConnsPerHost:       20,
			IdleConnTimeout:       90 * time.Second,
			ResponseHeaderTimeout: core.ResponseHeaderTimeout,
			ForceAttemptHTTP2:     true,
		},
	}
}

func initHTTPClient() {
	runtimeMutex.Lock()
	defer runtimeMutex.Unlock()

	client = newHTTPClient()
	initRegistryLocked()
}

// ensureInitialized lazily bootstraps the HTTP client and service registry.
// It preserves a test-supplied client while still making the registry usable.
func ensureInitialized() {
	runtimeMutex.Lock()
	defer runtimeMutex.Unlock()

	if client == nil {
		client = newHTTPClient()
	}
	if registry == nil {
		initRegistryLocked()
	}
}

func initRegistryLocked() {
	registry = services.NewRegistry()
	registry.Register(imx.New(client))
	registry.Register(pixhost.New(client))
	registry.Register(vipr.New(client))
	registry.Register(turbo.New(client))
	registry.Register(imagebam.New(client))
	registry.Register(vipergirls.New(client))
}

// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

// Package services defines the plugin interface every image-service module must
// implement, along with optional capability interfaces and a central Registry.
package services

import (
	"context"

	"github.com/conniecombs/GolangVersion/core"
)

// ServiceModule is the base interface every service plugin must satisfy.
type ServiceModule interface {
	// ID returns the canonical service identifier (e.g. "imx.to").
	ID() string
}

// Uploader is implemented by services that support direct (legacy) uploads.
type Uploader interface {
	Upload(ctx context.Context, fp string, job *core.JobRequest) (string, string, error)
}

// Authenticator is implemented by services that require a login step.
type Authenticator interface {
	Login(creds map[string]string) bool
}

// GalleryLister is implemented by services that can enumerate galleries.
type GalleryLister interface {
	ListGalleries(creds map[string]string) []map[string]string
}

// GalleryCreator is implemented by services that support gallery creation.
// Returns (id, data, error) — data may carry extra fields (e.g. upload hash).
type GalleryCreator interface {
	CreateGallery(creds map[string]string, name string) (string, interface{}, error)
}

// GalleryFinalizer is implemented by services that need a finalization step
// after all images have been uploaded to a gallery.
type GalleryFinalizer interface {
	FinalizeGallery(config map[string]string) error
}

// ForumService is implemented by forum-posting services (e.g. ViperGirls).
type ForumService interface {
	// LoginForum logs into the forum and returns (success, message).
	LoginForum(creds map[string]string) (bool, string)
	// Post submits a reply to a thread and returns (success, message).
	Post(config map[string]string) (bool, string)
}

// Registry maps service IDs to their module implementations.
type Registry struct {
	modules map[string]ServiceModule
}

func NewRegistry() *Registry {
	return &Registry{modules: make(map[string]ServiceModule)}
}

// Register adds a module to the registry under its ID.
func (r *Registry) Register(m ServiceModule) {
	r.modules[m.ID()] = m
}

// Get returns the module registered under id, or (nil, false).
func (r *Registry) Get(id string) (ServiceModule, bool) {
	m, ok := r.modules[id]
	return m, ok
}

// All returns a read-only snapshot of all registered modules.
func (r *Registry) All() map[string]ServiceModule {
	out := make(map[string]ServiceModule, len(r.modules))
	for k, v := range r.modules {
		out[k] = v
	}
	return out
}

// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import "github.com/conniecombs/GolangVersion/services"

func handleLoginVerify(job JobRequest) {
	ensureInitialized()
	svc, ok := registry.Get(job.Service)
	if !ok {
		sendJSON(OutputEvent{Type: "result", Status: "success", Msg: "No login required"})
		return
	}
	auth, ok := svc.(services.Authenticator)
	if !ok {
		sendJSON(OutputEvent{Type: "result", Status: "success", Msg: "No login required"})
		return
	}
	if auth.Login(job.Creds) {
		sendJSON(OutputEvent{Type: "result", Status: "success", Msg: "Login verified"})
		return
	}
	sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: "Login failed"})
}

func handleListGalleries(job JobRequest) {
	ensureInitialized()
	var galleries []map[string]string
	if svc, ok := registry.Get(job.Service); ok {
		if lister, ok := svc.(services.GalleryLister); ok {
			galleries = lister.ListGalleries(job.Creds)
		}
	}
	sendJSON(OutputEvent{Type: "data", Data: galleries, Status: "success"})
}

func handleCreateGallery(job JobRequest) {
	ensureInitialized()
	name := job.Config["gallery_name"]
	svc, ok := registry.Get(job.Service)
	if !ok {
		sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: "service not supported"})
		return
	}
	creator, ok := svc.(services.GalleryCreator)
	if !ok {
		sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: "service does not support gallery creation"})
		return
	}
	id, data, err := creator.CreateGallery(job.Creds, name)
	if err != nil {
		sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: err.Error()})
		return
	}
	sendJSON(OutputEvent{Type: "result", Status: "success", Msg: id, Data: data})
}

func handleFinalizeGallery(job JobRequest) {
	ensureInitialized()
	uploadHash := job.Config["gallery_upload_hash"]
	galleryHash := job.Config["gallery_hash"]
	if uploadHash == "" || galleryHash == "" {
		sendJSON(OutputEvent{Type: "error", Msg: "Missing gallery hashes"})
		return
	}

	if svc, ok := registry.Get(job.Service); ok {
		if finalizer, ok := svc.(services.GalleryFinalizer); ok {
			if err := finalizer.FinalizeGallery(job.Config); err != nil {
				sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: err.Error()})
				return
			}
		}
	}
	sendJSON(OutputEvent{Type: "result", Status: "success", Msg: "Gallery finalized"})
}

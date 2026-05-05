// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"fmt"
	"image"
	"image/jpeg"
	"os"
	"path/filepath"
	"strconv"
	"sync"

	"github.com/disintegration/imaging"
	log "github.com/sirupsen/logrus"

	"github.com/conniecombs/GolangVersion/core"
	"github.com/conniecombs/GolangVersion/services"
	"github.com/conniecombs/GolangVersion/services/vipergirls"
)

const (
	defaultThumbWidth = 100
	minThumbWidth     = 1
	maxThumbWidth     = 512
)

func handleJob(job JobRequest) {
	ensureInitialized()
	defer func() {
		if r := recover(); r != nil {
			sendJSON(OutputEvent{Type: "error", Msg: fmt.Sprintf("Panic: %v", r)})
		}
	}()
	if err := core.ValidateJobRequest(&job); err != nil {
		sendJSON(OutputEvent{Type: "error", Msg: fmt.Sprintf("Invalid job: %v", err)})
		return
	}
	if job.RateLimits != nil {
		updateRateLimiter(job.Service, job.RateLimits)
	}
	if job.RetryConfig == nil {
		job.RetryConfig = getDefaultRetryConfig()
	}

	switch job.Action {
	case "upload":
		handleUpload(job)
	case "http_upload":
		handleHttpUpload(job)
	case "login", "verify":
		handleLoginVerify(job)
	case "list_galleries":
		handleListGalleries(job)
	case "create_gallery":
		handleCreateGallery(job)
	case "finalize_gallery":
		handleFinalizeGallery(job)
	case "viper_login":
		handleViperLogin(job)
	case "viper_post":
		handleViperPost(job)
	case "generate_thumb":
		handleGenerateThumb(job)
	default:
		sendJSON(OutputEvent{Type: "error", Msg: fmt.Sprintf("Unsupported action: %s", job.Action)})
	}
}

// ---------------------------------------------------------------------------
// Upload handlers
// ---------------------------------------------------------------------------

func handleUpload(job JobRequest) {
	filesChan := make(chan string, len(job.Files))
	maxWorkers := workerLimit(job.Config)
	var wg sync.WaitGroup
	for i := 0; i < maxWorkers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for fp := range filesChan {
				processFile(fp, &job)
			}
		}()
	}
	for _, f := range job.Files {
		filesChan <- f
	}
	close(filesChan)
	wg.Wait()
	sendJSON(OutputEvent{Type: "batch_complete", Status: "done"})
}

func handleHttpUpload(job JobRequest) {
	if job.HttpSpec == nil {
		sendJSON(OutputEvent{Type: "error", Msg: "http_upload requires http_spec field"})
		return
	}
	filesChan := make(chan string, len(job.Files))
	maxWorkers := workerLimit(job.Config)
	var wg sync.WaitGroup
	for i := 0; i < maxWorkers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for fp := range filesChan {
				processFileGeneric(fp, &job)
			}
		}()
	}
	for _, f := range job.Files {
		filesChan <- f
	}
	close(filesChan)
	wg.Wait()
	sendJSON(OutputEvent{Type: "batch_complete", Status: "done"})
}

func processFile(fp string, job *JobRequest) {
	ensureInitialized()
	ctx, cancel := context.WithTimeout(context.Background(), core.ClientTimeout)
	defer cancel()

	type result struct{ url, thumb string; err error }
	resultChan := make(chan result, 1)

	go func() {
		sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Uploading"})
		cfg := job.RetryConfig
		if cfg == nil {
			cfg = getDefaultRetryConfig()
		}

		type ur struct{ url, thumb string }
		res, err := retryWithBackoff(ctx, cfg, func() (ur, int, error) {
			svc, ok := registry.Get(job.Service)
			if !ok {
				return ur{}, 0, fmt.Errorf("unknown service: %s", job.Service)
			}
			uploader, ok := svc.(services.Uploader)
			if !ok {
				return ur{}, 0, fmt.Errorf("service %s does not support upload", job.Service)
			}
			imgURL, thumb, err := uploader.Upload(ctx, fp, job)
			return ur{imgURL, thumb}, extractStatusCode(err), err
		}, log.WithField("file", filepath.Base(fp)))

		select {
		case resultChan <- result{res.url, res.thumb, err}:
		case <-ctx.Done():
		}
	}()

	select {
	case res := <-resultChan:
		if res.err != nil {
			sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Failed"})
			sendJSON(OutputEvent{Type: "error", FilePath: fp, Msg: res.err.Error()})
		} else {
			sendJSON(OutputEvent{Type: "result", FilePath: fp, Url: res.url, Thumb: res.thumb})
			sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Done"})
		}
	case <-ctx.Done():
		sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Timeout"})
		sendJSON(OutputEvent{Type: "error", FilePath: fp, Msg: "Upload timed out"})
	}
}

func processFileGeneric(fp string, job *JobRequest) {
	ctx, cancel := context.WithTimeout(context.Background(), core.ClientTimeout)
	defer cancel()

	type result struct{ url, thumb string; err error }
	resultChan := make(chan result, 1)

	go func() {
		sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Uploading"})
		cfg := job.RetryConfig
		if cfg == nil {
			cfg = getDefaultRetryConfig()
		}

		type ur struct{ url, thumb string }
		res, err := retryWithBackoff(ctx, cfg, func() (ur, int, error) {
			imgURL, thumb, err := executeHttpUpload(ctx, fp, job)
			return ur{imgURL, thumb}, extractStatusCode(err), err
		}, log.WithField("file", filepath.Base(fp)))

		select {
		case resultChan <- result{res.url, res.thumb, err}:
		case <-ctx.Done():
		}
	}()

	select {
	case res := <-resultChan:
		if res.err != nil {
			sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Failed"})
			sendJSON(OutputEvent{Type: "error", FilePath: fp, Msg: res.err.Error()})
		} else {
			sendJSON(OutputEvent{Type: "result", FilePath: fp, Url: res.url, Thumb: res.thumb})
			sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Done"})
		}
	case <-ctx.Done():
		sendJSON(OutputEvent{Type: "status", FilePath: fp, Status: "Timeout"})
		sendJSON(OutputEvent{Type: "error", FilePath: fp, Msg: "Upload timed out"})
	}
}

// ---------------------------------------------------------------------------
// Auth / gallery handlers
// ---------------------------------------------------------------------------

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
	} else {
		sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: "Login failed"})
	}
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
	} else {
		sendJSON(OutputEvent{Type: "result", Status: "success", Msg: id, Data: data})
	}
}

func handleFinalizeGallery(job JobRequest) {
	ensureInitialized()
	uploadHash := job.Config["gallery_upload_hash"]
	galleryHash := job.Config["gallery_hash"]
	if uploadHash == "" || galleryHash == "" {
		sendJSON(OutputEvent{Type: "error", Msg: "Missing gallery hashes"})
		return
	}

	svc, ok := registry.Get(job.Service)
	if ok {
		if finalizer, ok := svc.(services.GalleryFinalizer); ok {
			if err := finalizer.FinalizeGallery(job.Config); err != nil {
				sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: err.Error()})
				return
			}
		}
	}
	sendJSON(OutputEvent{Type: "result", Status: "success", Msg: "Gallery finalized"})
}

// ---------------------------------------------------------------------------
// ViperGirls forum handlers
// ---------------------------------------------------------------------------

func handleViperLogin(job JobRequest) {
	ensureInitialized()
	svc, ok := registry.Get(vipergirls.ServiceID)
	if !ok {
		sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: "vipergirls module not registered"})
		return
	}
	forum, ok := svc.(services.ForumService)
	if !ok {
		sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: "vipergirls does not implement ForumService"})
		return
	}
	success, msg := forum.LoginForum(job.Creds)
	status := "failed"
	if success {
		status = "success"
	}
	sendJSON(OutputEvent{Type: "result", Status: status, Msg: msg})
}

func handleViperPost(job JobRequest) {
	ensureInitialized()
	svc, ok := registry.Get(vipergirls.ServiceID)
	if !ok {
		sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: "vipergirls module not registered"})
		return
	}
	forum, ok := svc.(services.ForumService)
	if !ok {
		sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: "vipergirls does not implement ForumService"})
		return
	}
	success, msg := forum.Post(job.Config)
	status := "failed"
	if success {
		status = "success"
	}
	sendJSON(OutputEvent{Type: "result", Status: status, Msg: msg})
}

// ---------------------------------------------------------------------------
// Thumbnail generation
// ---------------------------------------------------------------------------

func handleGenerateThumb(job JobRequest) {
	if len(job.Files) == 0 {
		sendJSON(OutputEvent{Type: "error", Msg: "No file provided"})
		return
	}
	w, err := strconv.Atoi(job.Config["width"])
	if err != nil || w <= 0 {
		w = defaultThumbWidth
	}
	if w < minThumbWidth {
		w = minThumbWidth
	}
	if w > maxThumbWidth {
		w = maxThumbWidth
	}

	fp := job.Files[0]
	f, err := os.Open(fp) // #nosec G304 -- path is validated before this action is issued.
	if err != nil {
		sendJSON(OutputEvent{Type: "error", Msg: "File not found"})
		return
	}
	defer f.Close()

	img, _, err := image.Decode(f)
	if err != nil {
		sendJSON(OutputEvent{Type: "error", Msg: "Decode failed"})
		return
	}
	thumb := imaging.Resize(img, w, 0, imaging.Lanczos)
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, thumb, &jpeg.Options{Quality: 70}); err != nil {
		sendJSON(OutputEvent{Type: "error", Msg: "Encode failed"})
		return
	}
	sendJSON(OutputEvent{
		Type:     "data",
		Data:     base64.StdEncoding.EncodeToString(buf.Bytes()),
		Status:   "success",
		FilePath: fp,
	})
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func workerLimit(config map[string]string) int {
	if w, err := strconv.Atoi(config["threads"]); err == nil && w > 0 {
		return w
	}
	return 2
}


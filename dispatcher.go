// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"fmt"

	"github.com/conniecombs/GolangVersion/core"
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

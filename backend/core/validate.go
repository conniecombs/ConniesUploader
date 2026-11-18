// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package core

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

// MaxUploadFileSize is the largest file the sidecar will upload: 100 MiB
// (104,857,600 bytes). frontend/modules/config.py MAX_FILE_SIZE must hold the
// same value; docs/TRANSPORT_CONTRACT.md records it and a contract test in
// frontend/tests/test_build_contract.py keeps the three in step.
const MaxUploadFileSize = 100 * 1024 * 1024

func ValidateFilePath(filePath string) error {
	if filePath == "" {
		return fmt.Errorf("file path cannot be empty")
	}
	absPath, err := filepath.Abs(filePath)
	if err != nil {
		return fmt.Errorf("invalid file path: %w", err)
	}
	for _, component := range strings.Split(filepath.ToSlash(filePath), "/") {
		if component == ".." {
			return fmt.Errorf("path traversal detected")
		}
	}
	fileInfo, err := os.Stat(absPath)
	if err != nil {
		return fmt.Errorf("cannot access file: %w", err)
	}
	if !fileInfo.Mode().IsRegular() {
		return fmt.Errorf("not a regular file")
	}
	if fileInfo.Size() > MaxUploadFileSize {
		return fmt.Errorf("file too large (limit %d MB)", MaxUploadFileSize/(1024*1024))
	}
	return nil
}

func ValidateServiceName(service string) error {
	if service == "" {
		return fmt.Errorf("service name cannot be empty")
	}
	if !regexp.MustCompile(`^[a-zA-Z0-9\.\-]+$`).MatchString(service) {
		return fmt.Errorf("invalid service name")
	}
	return nil
}

func ValidateJobRequest(job *JobRequest) error {
	validActions := map[string]bool{
		"http_upload": true, "http_request": true, "http_batch_resolve": true,
		"generate_thumb": true, "cancel": true,
	}
	if !validActions[job.Action] {
		return fmt.Errorf("invalid action: %s", job.Action)
	}
	if job.Action == "cancel" {
		if strings.TrimSpace(job.BatchID) == "" {
			return fmt.Errorf("cancel requires batch_id")
		}
		return nil
	}
	if job.Action != "generate_thumb" {
		if err := ValidateServiceName(job.Service); err != nil {
			return fmt.Errorf("invalid service: %w", err)
		}
	}
	if map[string]bool{"http_upload": true, "generate_thumb": true}[job.Action] {
		if len(job.Files) == 0 {
			return fmt.Errorf("no files provided")
		}
	}
	// Upload files are validated one at a time while the job runs so a single
	// bad path fails only itself. Thumbnail jobs carry exactly one path.
	if job.Action == "generate_thumb" {
		for _, fp := range job.Files {
			if err := ValidateFilePath(fp); err != nil {
				return err
			}
		}
	}
	return nil
}

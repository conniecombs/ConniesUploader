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
	const maxFileSize = 100 * 1024 * 1024
	if fileInfo.Size() > maxFileSize {
		return fmt.Errorf("file too large")
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
		"generate_thumb": true,
	}
	if !validActions[job.Action] {
		return fmt.Errorf("invalid action: %s", job.Action)
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

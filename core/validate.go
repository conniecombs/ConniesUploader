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
	if strings.Contains(filePath, "..") {
		return fmt.Errorf("path traversal detected")
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
		"upload": true, "http_upload": true, "login": true, "verify": true,
		"list_galleries": true, "create_gallery": true, "finalize_gallery": true,
		"generate_thumb": true, "viper_login": true, "viper_post": true,
	}
	if !validActions[job.Action] {
		return fmt.Errorf("invalid action: %s", job.Action)
	}
	if job.Action != "generate_thumb" {
		if err := ValidateServiceName(job.Service); err != nil {
			return fmt.Errorf("invalid service: %w", err)
		}
	}
	if map[string]bool{"upload": true, "http_upload": true, "generate_thumb": true}[job.Action] {
		if len(job.Files) == 0 {
			return fmt.Errorf("no files provided")
		}
		for _, fp := range job.Files {
			if err := ValidateFilePath(fp); err != nil {
				return err
			}
		}
	}
	return nil
}

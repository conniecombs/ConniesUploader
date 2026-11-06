// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestValidateFilePathAcceptsDoubleDotInsideName(t *testing.T) {
	path := filepath.Join(t.TempDir(), "photo..jpg")
	if err := os.WriteFile(path, []byte("x"), 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}
	if err := ValidateFilePath(path); err != nil {
		t.Fatalf("ValidateFilePath(%q) = %v, want nil", path, err)
	}
}

func TestValidateFilePathRejectsParentComponent(t *testing.T) {
	dir := t.TempDir()
	// Build the string by hand so filepath.Join does not clean the "..".
	path := dir + string(filepath.Separator) + "sub" + string(filepath.Separator) + ".." + string(filepath.Separator) + "x.jpg"
	err := ValidateFilePath(path)
	if err == nil || !strings.Contains(err.Error(), "path traversal") {
		t.Fatalf("ValidateFilePath(%q) = %v, want path traversal error", path, err)
	}
}

func TestValidateJobRequestDoesNotStatUploadFiles(t *testing.T) {
	job := &JobRequest{Action: "http_upload", Service: "example.host", Files: []string{"/nonexistent/a.jpg"}}
	if err := ValidateJobRequest(job); err != nil {
		t.Fatalf("ValidateJobRequest = %v, want nil (per-file validation happens at upload time)", err)
	}
}

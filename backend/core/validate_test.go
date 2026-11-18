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

func TestMaxUploadFileSizeIs100MiB(t *testing.T) {
	if MaxUploadFileSize != 100*1024*1024 {
		t.Fatalf("MaxUploadFileSize = %d, want %d", MaxUploadFileSize, 100*1024*1024)
	}
}

func TestValidateFilePathEnforcesMaxUploadFileSize(t *testing.T) {
	dir := t.TempDir()
	atLimit := filepath.Join(dir, "at-limit.jpg")
	overLimit := filepath.Join(dir, "over-limit.jpg")
	for path, size := range map[string]int64{atLimit: MaxUploadFileSize, overLimit: MaxUploadFileSize + 1} {
		f, err := os.Create(path)
		if err != nil {
			t.Fatalf("create: %v", err)
		}
		// Truncate makes a sparse file, so no real 100 MiB write happens.
		if err := f.Truncate(size); err != nil {
			t.Fatalf("truncate: %v", err)
		}
		_ = f.Close()
	}

	if err := ValidateFilePath(atLimit); err != nil {
		t.Fatalf("file exactly at the limit rejected: %v", err)
	}
	err := ValidateFilePath(overLimit)
	if err == nil || !strings.Contains(err.Error(), "file too large") || !strings.Contains(err.Error(), "100 MB") {
		t.Fatalf("over-limit error = %v, want a 'file too large' error naming the 100 MB limit", err)
	}
}

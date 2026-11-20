// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"testing"
)

// The host turns spaces into underscores (as turboLikeHost does). "Scan 1.jpg"
// uploads first and is listed as "Scan_1.jpg": an EXACT match for the job's
// other file "Scan_1.jpg" and only a SIMILAR match for itself. A file that has
// not uploaded yet cannot be listed, so it must not hold that entry back; the
// first file takes its own entry and the second file later takes its own.
func TestNameMatchHoldsEntriesOnlyForFinishedUploads(t *testing.T) {
	host := newTurboLikeHost(t)
	defer host.server.Close()

	files := writeDistinctFiles(t, []string{"Scan 1.jpg", "x/Scan_1.jpg"})
	job := turboLikeJob(host.server.URL, files)
	for _, fp := range files {
		result, err := ExecuteHttpUploadWithData(context.Background(), host.server.Client(), fp, job)
		if err != nil {
			t.Errorf("%s: failed although the page lists its image: %v", fp, err)
			continue
		}
		if host.contentFor(t, result.URL) != mustReadFile(t, fp) {
			t.Errorf("%s got link %q, which is another file's image", fp, result.URL)
		}
	}
}

// A file whose upload failed is never listed and never claims, so it holds
// nothing back either.
func TestNameMatchIgnoresFilesWhoseUploadFailed(t *testing.T) {
	host := newTurboLikeHost(t)
	defer host.server.Close()

	files := writeDistinctFiles(t, []string{"Scan 1.jpg", "x/Scan_1.jpg"})
	job := turboLikeJob(host.server.URL, files)
	// The host refuses Scan_1.jpg (a 404 from an unknown upload path).
	refused := *job
	spec := *job.HttpSpec
	spec.URL = host.server.URL + "/refused"
	refused.HttpSpec = &spec
	if _, err := ExecuteHttpUploadWithData(context.Background(), host.server.Client(), files[1], &refused); err == nil {
		t.Fatal("refused upload succeeded")
	}
	result, err := ExecuteHttpUploadWithData(context.Background(), host.server.Client(), files[0], job)
	if err != nil {
		t.Fatalf("%s: failed although the page lists its image: %v", files[0], err)
	}
	if host.contentFor(t, result.URL) != mustReadFile(t, files[0]) {
		t.Fatalf("%s got link %q, which is another file's image", files[0], result.URL)
	}
}

// An entry is held back for a file whose upload finished and that has not
// claimed yet, when that file matches it better; equal matches go by upload
// order.
func TestNameMatchHoldsEntriesForFinishedUnclaimedFiles(t *testing.T) {
	entry := func(id, name string) resolveEntry {
		return resolveEntry{ImageURL: "https://img.example/p/" + id + "/" + name + ".html", ThumbURL: "https://thumbs.example/" + id}
	}
	names := map[string]string{"/in/Scan 1.jpg": "Scan 1.jpg", "/x/Scan_1.jpg": "Scan_1.jpg"}

	t.Run("better match finished", func(t *testing.T) {
		state := newResolveState()
		state.recordFinished("/x/Scan_1.jpg")
		state.recordFinished("/in/Scan 1.jpg")
		matcher := newResolveMatcher("filename", names, state)
		got := matcher.assign([]resolveEntry{entry("1", "Scan_1.jpg")}, []string{"/in/Scan 1.jpg"}, true)
		if len(got) != 0 {
			t.Fatalf("Scan 1.jpg took %v, which the finished Scan_1.jpg matches exactly", got)
		}
	})

	t.Run("equal matches by upload order", func(t *testing.T) {
		same := map[string]string{"/a/01.jpg": "01.jpg", "/b/01.jpg": "01.jpg", "/c/01.jpg": "01.jpg"}
		state := newResolveState()
		state.recordFinished("/b/01.jpg")
		state.recordFinished("/a/01.jpg")
		matcher := newResolveMatcher("filename", same, state)
		entries := []resolveEntry{entry("1", "01.jpg"), entry("2", "01.jpg")}
		got := matcher.assign(entries, []string{"/a/01.jpg"}, false)
		if got["/a/01.jpg"].ImageURL != entries[1].ImageURL {
			t.Fatalf("/a/01.jpg finished second but got %v, want the second entry", got)
		}
		got = matcher.assign(entries, []string{"/b/01.jpg"}, false)
		if got["/b/01.jpg"].ImageURL != entries[0].ImageURL {
			t.Fatalf("/b/01.jpg finished first but got %v, want the first entry", got)
		}
	})
}

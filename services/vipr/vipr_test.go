// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package vipr

import "testing"

func TestFolderIDFromHrefSupportsSemicolonSeparator(t *testing.T) {
	id := folderIDFromHref("?op=my_files;fld_id=104485")
	if id != "104485" {
		t.Fatalf("expected semicolon-separated folder id, got %q", id)
	}
}

func TestFolderIDFromHrefSupportsAmpersandSeparator(t *testing.T) {
	id := folderIDFromHref("?op=my_files&fld_id=104486")
	if id != "104486" {
		t.Fatalf("expected ampersand-separated folder id, got %q", id)
	}
}

func TestFolderIDFromHrefDecodesEscapedID(t *testing.T) {
	id := folderIDFromHref("?op=my_files;fld_id=abc%20123")
	if id != "abc 123" {
		t.Fatalf("expected decoded folder id, got %q", id)
	}
}

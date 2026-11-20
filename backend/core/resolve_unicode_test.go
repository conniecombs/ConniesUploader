// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import "testing"

// macOS file names are often NFD (e + combining acute); hosts list NFC (é).
// Names are compared once both are NFC.
func TestNFDLocalNameMatchesNFCPageName(t *testing.T) {
	cases := []struct {
		local, page string
		want        int
	}{
		{"café.jpg", "café.jpg", exactMatch},
		{"café.jpg", "café.jpg", exactMatch},
		{"/in/Café 1.jpg", "café_1.jpg", similarMatch},
		{"café.jpg", "https://img.example/p/1/caf%C3%A9.jpg.html", exactMatch},
	}
	for _, tc := range cases {
		if got := nameMatch(pageNameForms(tc.page), localNameForms(tc.local)); got != tc.want {
			t.Errorf("local %q vs page %q: tier %d, want %d", tc.local, tc.page, got, tc.want)
		}
	}
}

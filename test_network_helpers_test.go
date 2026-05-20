// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import "testing"

func skipNetworkInShort(t *testing.T) {
	t.Helper()
	if testing.Short() {
		t.Skip("skipping network-dependent test in short mode")
	}
}

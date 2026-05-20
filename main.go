// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"flag"
	"os"
)

func main() {
	workerCount := flag.Int("workers", defaultSidecarWorkers, "Number of worker goroutines")
	flag.Parse()

	runSidecar(os.Stdin, *workerCount)
}

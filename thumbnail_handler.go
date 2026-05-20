// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"bytes"
	"encoding/base64"
	"image"
	"image/jpeg"
	"os"
	"strconv"

	"github.com/disintegration/imaging"
)

const (
	defaultThumbWidth = 100
	minThumbWidth     = 1
	maxThumbWidth     = 512
)

func handleGenerateThumb(job JobRequest) {
	if len(job.Files) == 0 {
		sendJSON(OutputEvent{Type: "error", Msg: "No file provided"})
		return
	}

	fp := job.Files[0]
	f, err := os.Open(fp) // #nosec G304 -- path is validated before this action is issued.
	if err != nil {
		sendJSON(OutputEvent{Type: "error", Msg: "File not found"})
		return
	}
	defer f.Close()

	img, _, err := image.Decode(f)
	if err != nil {
		sendJSON(OutputEvent{Type: "error", Msg: "Decode failed"})
		return
	}

	thumb := imaging.Resize(img, thumbnailWidth(job.Config), 0, imaging.Lanczos)
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, thumb, &jpeg.Options{Quality: 70}); err != nil {
		sendJSON(OutputEvent{Type: "error", Msg: "Encode failed"})
		return
	}
	sendJSON(OutputEvent{
		Type:     "data",
		Data:     base64.StdEncoding.EncodeToString(buf.Bytes()),
		Status:   "success",
		FilePath: fp,
	})
}

func thumbnailWidth(config map[string]string) int {
	width, err := strconv.Atoi(config["width"])
	if err != nil || width <= 0 {
		width = defaultThumbWidth
	}
	if width < minThumbWidth {
		return minThumbWidth
	}
	if width > maxThumbWidth {
		return maxThumbWidth
	}
	return width
}

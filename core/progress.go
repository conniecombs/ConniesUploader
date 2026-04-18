// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package core

import (
	"io"
	"sync"
	"time"
)

type ProgressWriter struct {
	writer         io.Writer
	totalBytes     int64
	bytesWritten   int64
	startTime      time.Time
	lastReportTime time.Time
	filePath       string
	mu             sync.Mutex
}

func NewProgressWriter(w io.Writer, totalBytes int64, filePath string) *ProgressWriter {
	now := time.Now()
	return &ProgressWriter{
		writer:         w,
		totalBytes:     totalBytes,
		startTime:      now,
		lastReportTime: now,
		filePath:       filePath,
	}
}

func (pw *ProgressWriter) Write(p []byte) (int, error) {
	n, err := pw.writer.Write(p)
	pw.mu.Lock()
	pw.bytesWritten += int64(n)
	bytesWritten := pw.bytesWritten
	totalBytes := pw.totalBytes
	now := time.Now()
	shouldReport := now.Sub(pw.lastReportTime) >= ProgressReportInterval
	if shouldReport {
		pw.lastReportTime = now
	}
	pw.mu.Unlock()

	if shouldReport {
		elapsed := now.Sub(pw.startTime).Seconds()
		speed := float64(bytesWritten) / elapsed
		percentage := (float64(bytesWritten) / float64(totalBytes)) * 100.0
		var eta int
		if speed > 0 {
			eta = int(float64(totalBytes-bytesWritten) / speed)
		}
		SendJSON(OutputEvent{
			Type:     "progress",
			FilePath: pw.filePath,
			Data: ProgressEvent{
				BytesTransferred: bytesWritten,
				TotalBytes:       totalBytes,
				Speed:            speed,
				Percentage:       percentage,
				ETA:              eta,
			},
		})
	}
	return n, err
}

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
	jobID          string
	reportedFirst  bool
	mu             sync.Mutex
}

func NewProgressWriter(w io.Writer, totalBytes int64, filePath string, jobID ...string) *ProgressWriter {
	now := time.Now()
	id := ""
	if len(jobID) > 0 {
		id = jobID[0]
	}
	return &ProgressWriter{
		writer:         w,
		totalBytes:     totalBytes,
		startTime:      now,
		lastReportTime: now,
		filePath:       filePath,
		jobID:          id,
	}
}

func (pw *ProgressWriter) Write(p []byte) (int, error) {
	n, err := pw.writer.Write(p)
	pw.mu.Lock()
	pw.bytesWritten += int64(n)
	bytesWritten := pw.bytesWritten
	totalBytes := pw.totalBytes
	now := time.Now()
	shouldReport := n > 0 && (!pw.reportedFirst ||
		now.Sub(pw.lastReportTime) >= ProgressReportInterval ||
		(totalBytes > 0 && bytesWritten >= totalBytes))
	if shouldReport {
		pw.reportedFirst = true
		pw.lastReportTime = now
	}
	pw.mu.Unlock()

	if shouldReport {
		elapsed := now.Sub(pw.startTime).Seconds()
		speed := 0.0
		if elapsed > 0 {
			speed = float64(bytesWritten) / elapsed
		}
		percentage := 0.0
		if totalBytes > 0 {
			percentage = (float64(bytesWritten) / float64(totalBytes)) * 100.0
			if percentage > 100.0 {
				percentage = 100.0
			}
		}
		var eta int
		if speed > 0 && totalBytes > bytesWritten {
			eta = int(float64(totalBytes-bytesWritten) / speed)
		}
		event := OutputEvent{
			Type:     "progress",
			FilePath: pw.filePath,
			Data: ProgressEvent{
				BytesTransferred: bytesWritten,
				TotalBytes:       totalBytes,
				Speed:            speed,
				Percentage:       percentage,
				ETA:              eta,
			},
		}
		if pw.jobID != "" {
			event.ID = pw.jobID
		}
		SendJSON(event)
	}
	return n, err
}

// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package main

import (
	"bufio"
	"encoding/json"
	"os"
	"strings"
	"sync"
	"testing"
)

// captureSidecarEvents runs fn while os.Stdout is redirected to a pipe and
// returns every JSON OutputEvent the sidecar printed, in order.
func captureSidecarEvents(t *testing.T, fn func()) []OutputEvent {
	t.Helper()
	oldStdout := os.Stdout
	reader, writer, err := os.Pipe()
	if err != nil {
		t.Fatalf("os.Pipe failed: %v", err)
	}
	os.Stdout = writer

	var events []OutputEvent
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		scanner := bufio.NewScanner(reader)
		scanner.Buffer(make([]byte, 0, 1024*1024), 16*1024*1024)
		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			if line == "" {
				continue
			}
			var event OutputEvent
			if err := json.Unmarshal([]byte(line), &event); err != nil {
				continue
			}
			events = append(events, event)
		}
	}()

	func() {
		defer func() {
			_ = writer.Close()
			os.Stdout = oldStdout
		}()
		fn()
	}()
	wg.Wait()
	_ = reader.Close()
	return events
}

func eventsOfType(events []OutputEvent, eventType string) []OutputEvent {
	var matched []OutputEvent
	for _, event := range events {
		if event.Type == eventType {
			matched = append(matched, event)
		}
	}
	return matched
}

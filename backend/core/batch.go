// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"sync"
)

// batchEntry tracks the shared context for every job of one Python batch.
type batchEntry struct {
	ctx    context.Context
	cancel context.CancelFunc
	refs   int
}

var (
	batchMu        sync.Mutex
	liveBatches    = map[string]*batchEntry{}
	cancelledBatch = map[string]bool{}
)

// RegisterBatch returns a context shared by every job of batchID and a
// release func the caller must invoke when its job finishes. A batch that
// was cancelled before registration starts with an already-cancelled
// context. An empty id is not tracked and yields a live background context.
func RegisterBatch(batchID string) (context.Context, func()) {
	if batchID == "" {
		return context.Background(), func() {}
	}

	batchMu.Lock()
	defer batchMu.Unlock()

	entry := liveBatches[batchID]
	if entry == nil {
		ctx, cancel := context.WithCancel(context.Background())
		entry = &batchEntry{ctx: ctx, cancel: cancel}
		liveBatches[batchID] = entry
		if cancelledBatch[batchID] {
			cancel()
		}
	}
	entry.refs++

	var once sync.Once
	release := func() {
		once.Do(func() {
			batchMu.Lock()
			defer batchMu.Unlock()
			entry.refs--
			if entry.refs <= 0 {
				entry.cancel()
				if liveBatches[batchID] == entry {
					delete(liveBatches, batchID)
				}
			}
		})
	}
	return entry.ctx, release
}

// CancelBatch cancels every live job of batchID and remembers the id so
// jobs still queued for it are skipped. It reports whether a live batch
// was cancelled.
func CancelBatch(batchID string) bool {
	if batchID == "" {
		return false
	}

	batchMu.Lock()
	defer batchMu.Unlock()

	cancelledBatch[batchID] = true
	entry := liveBatches[batchID]
	if entry == nil {
		return false
	}
	entry.cancel()
	return true
}

// BatchCancelled reports whether CancelBatch was called for batchID.
func BatchCancelled(batchID string) bool {
	if batchID == "" {
		return false
	}
	batchMu.Lock()
	defer batchMu.Unlock()
	return cancelledBatch[batchID]
}

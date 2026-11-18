// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"sync"
	"time"
)

// cancelledBatchTTL bounds how long a cancelled batch id is remembered so
// jobs still queued for it are skipped. Python starts a new batch id per
// upload, so an hour is far longer than any queue wait while keeping the
// set from growing for the life of the sidecar.
const cancelledBatchTTL = time.Hour

// batchNow is the clock used for cancelled-batch expiry (replaced in tests).
var batchNow = time.Now

// batchEntry tracks the shared context for every job of one Python batch.
type batchEntry struct {
	ctx    context.Context
	cancel context.CancelFunc
	refs   int
}

var (
	batchMu        sync.Mutex
	liveBatches    = map[string]*batchEntry{}
	cancelledBatch = map[string]time.Time{}
)

// pruneCancelledLocked drops cancelled ids older than cancelledBatchTTL.
// Callers must hold batchMu.
func pruneCancelledLocked() {
	cutoff := batchNow().Add(-cancelledBatchTTL)
	for id, at := range cancelledBatch {
		if at.Before(cutoff) {
			delete(cancelledBatch, id)
		}
	}
}

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
	pruneCancelledLocked()

	entry := liveBatches[batchID]
	if entry == nil {
		ctx, cancel := context.WithCancel(context.Background())
		entry = &batchEntry{ctx: ctx, cancel: cancel}
		liveBatches[batchID] = entry
		if _, cancelled := cancelledBatch[batchID]; cancelled {
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
	pruneCancelledLocked()

	cancelledBatch[batchID] = batchNow()
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
	_, cancelled := cancelledBatch[batchID]
	return cancelled
}

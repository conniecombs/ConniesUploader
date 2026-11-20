// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"fmt"
	"sync/atomic"
	"testing"
	"time"
)

// batchTestSeq numbers the batch ids the tests use. Cancelled ids are global
// state that outlives a test, so a fixed id would make the next run of the
// same test (go test -count=N) start with its batch already cancelled.
var batchTestSeq atomic.Int64

func uniqueBatchID(prefix string) string {
	return fmt.Sprintf("%s-%d", prefix, batchTestSeq.Add(1))
}

func TestCancelBatchCancelsRegisteredContext(t *testing.T) {
	id := uniqueBatchID("b1")
	ctx, release := RegisterBatch(id)
	defer release()
	if ctx.Err() != nil {
		t.Fatalf("fresh batch context already done: %v", ctx.Err())
	}
	if !CancelBatch(id) {
		t.Fatalf("CancelBatch(%s) = false, want true for a live batch", id)
	}
	if ctx.Err() != context.Canceled {
		t.Fatalf("ctx.Err() = %v, want context.Canceled", ctx.Err())
	}
}

func TestBatchCancelledPersistsForLaterJobs(t *testing.T) {
	id := uniqueBatchID("b2")
	if CancelBatch(id) {
		t.Fatalf("CancelBatch(%s) = true, want false when no job is live", id)
	}
	if !BatchCancelled(id) {
		t.Fatalf("BatchCancelled(%s) = false, want true after cancel", id)
	}
	ctx, release := RegisterBatch(id)
	defer release()
	if ctx.Err() != context.Canceled {
		t.Fatalf("a job registered after cancel must start cancelled; got %v", ctx.Err())
	}
}

func TestCancelUnknownBatchIsNoop(t *testing.T) {
	if CancelBatch("") {
		t.Fatalf("CancelBatch(\"\") = true, want false")
	}
	if id := uniqueBatchID("nope"); CancelBatch(id) {
		t.Fatalf("CancelBatch(%s) = true, want false", id)
	}
	ctx, release := RegisterBatch("")
	defer release()
	if ctx.Err() != nil {
		t.Fatalf("empty batch id must yield a live background context")
	}
}

func TestCancelledBatchIDsArePrunedAfterTTL(t *testing.T) {
	start := time.Date(2026, 11, 18, 12, 0, 0, 0, time.UTC)
	now := start
	oldNow := batchNow
	batchNow = func() time.Time { return now }
	defer func() { batchNow = oldNow }()

	CancelBatch("stale")
	if !BatchCancelled("stale") {
		t.Fatalf("freshly cancelled batch must be remembered")
	}

	now = start.Add(cancelledBatchTTL - time.Minute)
	CancelBatch("trigger-prune-early")
	if !BatchCancelled("stale") {
		t.Fatalf("cancelled batch forgotten before its TTL")
	}

	now = start.Add(cancelledBatchTTL + time.Minute)
	_, release := RegisterBatch("new-batch")
	release()
	if BatchCancelled("stale") {
		t.Fatalf("cancelled batch still remembered after its TTL")
	}
	if !BatchCancelled("trigger-prune-early") {
		t.Fatalf("batch cancelled within the TTL was pruned too early")
	}
}

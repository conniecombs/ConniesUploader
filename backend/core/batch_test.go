// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"testing"
	"time"
)

func TestCancelBatchCancelsRegisteredContext(t *testing.T) {
	ctx, release := RegisterBatch("b1")
	defer release()
	if ctx.Err() != nil {
		t.Fatalf("fresh batch context already done: %v", ctx.Err())
	}
	if !CancelBatch("b1") {
		t.Fatalf("CancelBatch(b1) = false, want true for a live batch")
	}
	if ctx.Err() != context.Canceled {
		t.Fatalf("ctx.Err() = %v, want context.Canceled", ctx.Err())
	}
}

func TestBatchCancelledPersistsForLaterJobs(t *testing.T) {
	if CancelBatch("b2") {
		t.Fatalf("CancelBatch(b2) = true, want false when no job is live")
	}
	if !BatchCancelled("b2") {
		t.Fatalf("BatchCancelled(b2) = false, want true after cancel")
	}
	ctx, release := RegisterBatch("b2")
	defer release()
	if ctx.Err() != context.Canceled {
		t.Fatalf("a job registered after cancel must start cancelled; got %v", ctx.Err())
	}
}

func TestCancelUnknownBatchIsNoop(t *testing.T) {
	if CancelBatch("") {
		t.Fatalf("CancelBatch(\"\") = true, want false")
	}
	if CancelBatch("nope") {
		t.Fatalf("CancelBatch(nope) = true, want false")
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

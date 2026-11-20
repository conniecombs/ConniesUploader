package main

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"
)

// A malformed request line is reported once and the next line is still read.
// The JSON decoder's error is sticky, so decoding the stream object by object
// used to report the same error forever and never read another request.
func TestMalformedRequestLineIsSkipped(t *testing.T) {
	good, _ := json.Marshal(JobRequest{ID: "after", Action: "cancel", BatchID: "b-after"})
	input := strings.NewReader("{not json\n" + string(good) + "\n")

	done := make(chan struct{})
	var events []OutputEvent
	go func() {
		defer close(done)
		events = captureSidecarEvents(t, func() {
			runSidecar(input, 1, make(chan struct{}))
		})
	}()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("sidecar kept looping on a malformed request line")
	}

	decodeErrors := 0
	sawGood := false
	for _, event := range events {
		if event.Type == "error" && strings.Contains(event.Msg, "JSON decode error") {
			decodeErrors++
		}
		if event.ID == "after" {
			sawGood = true
		}
	}
	if decodeErrors != 1 {
		t.Fatalf("decode errors = %d, want 1 (events %+v)", decodeErrors, events)
	}
	if !sawGood {
		t.Fatalf("the request after the malformed line was never handled: %+v", events)
	}
}

// A file waiting for a service-wide upload slot gives up when its batch is cancelled.
func TestLimiterWaitEndsWhenBatchIsCancelled(t *testing.T) {
	limiter := newServiceUploadLimiter()
	if !limiter.acquire(context.Background(), 1) {
		t.Fatal("first acquire failed")
	}
	ctx, cancel := context.WithCancel(context.Background())
	got := make(chan bool, 1)
	go func() { got <- limiter.acquire(ctx, 1) }()
	time.Sleep(50 * time.Millisecond)
	cancel()
	select {
	case ok := <-got:
		if ok {
			t.Fatal("acquire succeeded after cancel without a free slot")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("acquire kept waiting after its batch was cancelled")
	}
	limiter.release()
	if !limiter.acquire(context.Background(), 1) {
		t.Fatal("slot was not free after release")
	}
}

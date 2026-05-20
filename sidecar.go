// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/signal"
	"sync"
	"syscall"

	log "github.com/sirupsen/logrus"
)

const (
	defaultSidecarWorkers = 8
	jobQueueBuffer        = 100
	minSidecarWorkers     = 1
	maxSidecarWorkers     = 16
)

type decodedJob struct {
	job JobRequest
	err error
}

func clampSidecarWorkers(workers int) int {
	if workers < minSidecarWorkers {
		return minSidecarWorkers
	}
	if workers > maxSidecarWorkers {
		return maxSidecarWorkers
	}
	return workers
}

func runSidecar(input io.Reader, requestedWorkerCount int) {
	workerCount := clampSidecarWorkers(requestedWorkerCount)
	if workerCount != requestedWorkerCount {
		log.WithFields(log.Fields{
			"requested": requestedWorkerCount,
			"effective": workerCount,
		}).Warn("sidecar worker count clamped")
	}

	log.WithField("workers", workerCount).Info("Go sidecar starting")
	sendJSON(OutputEvent{Type: "log", Msg: fmt.Sprintf("=== GO SIDECAR STARTED - WORKERS: %d ===", workerCount)})

	initHTTPClient()

	jobQueue := make(chan JobRequest, jobQueueBuffer)
	var wg sync.WaitGroup
	startSidecarWorkers(workerCount, jobQueue, &wg)

	shutdownChan := make(chan struct{})
	var shutdownOnce sync.Once
	requestShutdown := func() {
		shutdownOnce.Do(func() {
			close(shutdownChan)
		})
	}

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(sigChan)
	go func() {
		select {
		case <-sigChan:
			requestShutdown()
		case <-shutdownChan:
		}
	}()

	decodedJobs := make(chan decodedJob)
	go decodeJobs(input, decodedJobs)

	for {
		select {
		case <-shutdownChan:
			goto shutdown
		case decoded, ok := <-decodedJobs:
			if !ok {
				requestShutdown()
				goto shutdown
			}
			if decoded.err != nil {
				sendJSON(OutputEvent{Type: "error", Msg: fmt.Sprintf("JSON decode error: %v", decoded.err)})
				continue
			}
			select {
			case jobQueue <- decoded.job:
			case <-shutdownChan:
				goto shutdown
			}
		}
	}

shutdown:
	close(jobQueue)
	wg.Wait()
	sendJSON(OutputEvent{Type: "log", Msg: "=== GO SIDECAR SHUTDOWN COMPLETE ==="})
}

func startSidecarWorkers(workerCount int, jobQueue <-chan JobRequest, wg *sync.WaitGroup) {
	for i := 0; i < workerCount; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for job := range jobQueue {
				handleJob(job)
			}
		}()
	}
}

func decodeJobs(input io.Reader, out chan<- decodedJob) {
	defer close(out)

	decoder := json.NewDecoder(input)
	for {
		var job JobRequest
		if err := decoder.Decode(&job); err != nil {
			if err == io.EOF {
				return
			}
			out <- decodedJob{err: err}
			continue
		}
		out <- decodedJob{job: job}
	}
}

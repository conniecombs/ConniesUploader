// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"

	log "github.com/sirupsen/logrus"
)

// ScheduledPost represents a forum post scheduled for future delivery.
type ScheduledPost struct {
	ID            string `json:"id"`
	ThreadID      string `json:"thread_id"`
	ThreadName    string `json:"thread_name"`
	Message       string `json:"message"`
	ScheduledTime string `json:"scheduled_time"` // RFC3339
	Status        string `json:"status"`         // "pending", "posted", "failed"
	Error         string `json:"error,omitempty"`
	Cover         string `json:"cover_thumbnail,omitempty"`
}

// PostFunc is the function signature the scheduler calls to execute a post.
// It receives thread_id and message, returns (success, error_message).
type PostFunc func(ctx context.Context, client *http.Client, threadID, message string) (bool, string)

// Scheduler manages scheduled forum posts, persisting them to disk and
// executing them via a generic PostFunc when their time arrives.
type Scheduler struct {
	mu       sync.Mutex
	posts    []ScheduledPost
	filePath string
	client   *http.Client
	postFn   PostFunc
}

// GlobalScheduler is the package-level scheduler singleton.
var GlobalScheduler *Scheduler

// InitScheduler creates and starts the global scheduler.
// postFn is called to actually execute a post when the scheduled time arrives.
func InitScheduler(client *http.Client, postFn PostFunc) {
	home, err := os.UserHomeDir()
	if err != nil {
		home = "."
	}
	path := filepath.Join(home, ".conniesuploader", "scheduled_posts.json")

	GlobalScheduler = &Scheduler{
		posts:    make([]ScheduledPost, 0),
		filePath: path,
		client:   client,
		postFn:   postFn,
	}
	GlobalScheduler.Load()

	go GlobalScheduler.Run()
}

// Load reads scheduled posts from disk.
func (s *Scheduler) Load() {
	s.mu.Lock()
	defer s.mu.Unlock()

	data, err := os.ReadFile(s.filePath)
	if err != nil {
		if !os.IsNotExist(err) {
			log.WithError(err).Warn("Failed to read scheduled_posts.json")
		}
		return
	}
	if err := json.Unmarshal(data, &s.posts); err != nil {
		log.WithError(err).Warn("Failed to parse scheduled_posts.json")
	}
}

func (s *Scheduler) saveLocked() {
	data, err := json.MarshalIndent(s.posts, "", "  ")
	if err != nil {
		log.WithError(err).Error("Failed to marshal scheduled posts")
		return
	}
	_ = os.MkdirAll(filepath.Dir(s.filePath), 0755)
	if err := os.WriteFile(s.filePath, data, 0644); err != nil {
		log.WithError(err).Error("Failed to save scheduled_posts.json")
	}
}

// Save persists scheduled posts to disk.
func (s *Scheduler) Save() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.saveLocked()
}

// AddPost enqueues a new scheduled post.
func (s *Scheduler) AddPost(post ScheduledPost) {
	s.mu.Lock()
	defer s.mu.Unlock()
	post.Status = "pending"
	s.posts = append(s.posts, post)
	s.saveLocked()
}

// CancelPost removes a pending scheduled post by ID.
func (s *Scheduler) CancelPost(id string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	for i, p := range s.posts {
		if p.ID == id && p.Status == "pending" {
			s.posts = append(s.posts[:i], s.posts[i+1:]...)
			s.saveLocked()
			return true
		}
	}
	return false
}

// ListPosts returns a copy of all scheduled posts.
func (s *Scheduler) ListPosts() []ScheduledPost {
	s.mu.Lock()
	defer s.mu.Unlock()
	cp := make([]ScheduledPost, len(s.posts))
	copy(cp, s.posts)
	return cp
}

// Run checks every minute for posts that are due and executes them.
func (s *Scheduler) Run() {
	ticker := time.NewTicker(time.Minute)
	defer ticker.Stop()

	// Run immediately once on startup.
	s.checkAndPost()

	for range ticker.C {
		s.checkAndPost()
	}
}

func (s *Scheduler) checkAndPost() {
	s.mu.Lock()
	now := time.Now()
	var toPostIDs []string
	for _, p := range s.posts {
		if p.Status == "pending" {
			t, err := time.Parse(time.RFC3339, p.ScheduledTime)
			if err == nil && !now.Before(t) {
				toPostIDs = append(toPostIDs, p.ID)
			}
		}
	}
	s.mu.Unlock()

	if len(toPostIDs) == 0 {
		return
	}

	for _, id := range toPostIDs {
		s.mu.Lock()
		var postCopy ScheduledPost
		found := false
		for _, p := range s.posts {
			if p.ID == id && p.Status == "pending" {
				postCopy = p
				found = true
				break
			}
		}
		s.mu.Unlock()

		if !found {
			continue // Post might have been cancelled.
		}

		log.Infof("Scheduler: Executing scheduled post %s for thread %s", postCopy.ID, postCopy.ThreadID)

		ctx, cancel := context.WithTimeout(context.Background(), ClientTimeout)
		success, msg := s.postFn(ctx, s.client, postCopy.ThreadID, postCopy.Message)
		cancel()

		s.mu.Lock()
		found = false
		for i, p := range s.posts {
			if p.ID == id {
				if success {
					s.posts[i].Status = "posted"
					s.posts[i].Error = ""
				} else {
					s.posts[i].Status = "failed"
					s.posts[i].Error = msg
				}
				postCopy = s.posts[i]
				found = true
				break
			}
		}
		if found {
			s.saveLocked()
		}
		s.mu.Unlock()

		if found {
			// Emit event back to Python.
			SendJSON(OutputEvent{
				Type:   "scheduled_post_completed",
				ID:     postCopy.ID,
				Status: postCopy.Status,
				Msg:    msg,
				Data:   postCopy,
			})
		}
	}
}

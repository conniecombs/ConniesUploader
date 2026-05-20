// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"github.com/conniecombs/GolangVersion/services"
	"github.com/conniecombs/GolangVersion/services/vipergirls"
)

func handleViperLogin(job JobRequest) {
	ensureInitialized()
	forum, ok := getViperGirlsForum()
	if !ok {
		return
	}
	success, msg := forum.LoginForum(job.Creds)
	sendForumResult(success, msg)
}

func handleViperPost(job JobRequest) {
	ensureInitialized()
	forum, ok := getViperGirlsForum()
	if !ok {
		return
	}
	success, msg := forum.Post(job.Config)
	sendForumResult(success, msg)
}

func getViperGirlsForum() (services.ForumService, bool) {
	svc, ok := registry.Get(vipergirls.ServiceID)
	if !ok {
		sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: "vipergirls module not registered"})
		return nil, false
	}
	forum, ok := svc.(services.ForumService)
	if !ok {
		sendJSON(OutputEvent{Type: "result", Status: "failed", Msg: "vipergirls does not implement ForumService"})
		return nil, false
	}
	return forum, true
}

func sendForumResult(success bool, msg string) {
	status := "failed"
	if success {
		status = "success"
	}
	sendJSON(OutputEvent{Type: "result", Status: status, Msg: msg})
}

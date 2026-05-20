// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"os"

	log "github.com/sirupsen/logrus"
)

func init() {
	log.SetFormatter(&log.JSONFormatter{
		TimestampFormat: "2006-01-02 15:04:05",
		FieldMap: log.FieldMap{
			log.FieldKeyTime:  "timestamp",
			log.FieldKeyLevel: "level",
			log.FieldKeyMsg:   "message",
		},
	})
	log.SetOutput(os.Stderr)
	log.SetLevel(log.InfoLevel)
}

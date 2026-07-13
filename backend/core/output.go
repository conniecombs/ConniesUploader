// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package core

import (
	"encoding/json"
	"fmt"
	"sync"
)

var outputMutex sync.Mutex

func SendJSON(v interface{}) {
	outputMutex.Lock()
	defer outputMutex.Unlock()
	b, _ := json.Marshal(v)
	fmt.Println(string(b))
}

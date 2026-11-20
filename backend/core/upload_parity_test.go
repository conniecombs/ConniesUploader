// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
)

// The cases in testdata/upload_parity.json pin what the legacy Go upload path
// reports today. frontend/tests/test_upload_parity.py runs the same cases
// through the Python port and the migrated host plugins, so a difference
// between the two paths fails one of the suites.

type parityFixture struct {
	FailureMessages []struct {
		Name    string   `json:"name"`
		Reason  string   `json:"reason"`
		Status  int      `json:"status"`
		Body    string   `json:"body"`
		Secrets []string `json:"secrets"`
		Want    string   `json:"want"`
	} `json:"failure_messages"`
	JSONUploads []struct {
		Name    string             `json:"name"`
		Parser  ResponseParserSpec `json:"parser"`
		File    string             `json:"file"`
		Status  int                `json:"status"`
		Body    string             `json:"body"`
		Secrets []string           `json:"secrets"`
		Want    struct {
			URL   string `json:"url"`
			Thumb string `json:"thumb"`
			Error string `json:"error"`
		} `json:"want"`
	} `json:"json_uploads"`
}

func loadParityFixture(t *testing.T) parityFixture {
	t.Helper()
	data, err := os.ReadFile("testdata/upload_parity.json")
	if err != nil {
		t.Fatalf("read fixture: %v", err)
	}
	var fixture parityFixture
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatalf("decode fixture: %v", err)
	}
	return fixture
}

func secretsJob(secrets []string) *JobRequest {
	creds := make(map[string]string, len(secrets))
	for i, secret := range secrets {
		creds[fmt.Sprintf("secret%d", i)] = secret
	}
	return &JobRequest{Creds: creds}
}

func TestParityFailureMessages(t *testing.T) {
	for _, tc := range loadParityFixture(t).FailureMessages {
		got := uploadFailure(tc.Reason, tc.Status, []byte(tc.Body), uploadSecrets(secretsJob(tc.Secrets), nil)).Error()
		if got != tc.Want {
			t.Errorf("%s:\n got %q\nwant %q", tc.Name, got, tc.Want)
		}
	}
}

func TestParityJSONUploads(t *testing.T) {
	fp := writeUploadTestFile(t, t.TempDir(), "photo.jpg", 64)
	for _, tc := range loadParityFixture(t).JSONUploads {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			_, _ = io.Copy(io.Discard, r.Body)
			w.WriteHeader(tc.Status)
			_, _ = w.Write([]byte(tc.Body))
		}))
		job := jsonUploadJob(server.URL, fp, tc.Parser)
		job.Creds = secretsJob(tc.Secrets).Creds
		// The Python path never retries an upload because of its status.
		job.RetryConfig.RetryableHTTPCodes = nil
		// Templates read the local file name, so parse as the fixture's file.
		result, err := ExecuteHttpUploadWithData(context.Background(), server.Client(), fp, job)
		server.Close()
		if tc.Parser.URLTemplate != "" && err == nil {
			parsedURL, parsedThumb, _ := parseHttpResponseBody([]byte(tc.Body), &tc.Parser, tc.File)
			result.URL, result.Thumb = parsedURL, parsedThumb
		}
		gotErr := ""
		if err != nil {
			gotErr = err.Error()
		}
		if result.URL != tc.Want.URL || result.Thumb != tc.Want.Thumb || gotErr != tc.Want.Error {
			t.Errorf("%s:\n got url=%q thumb=%q err=%q\nwant url=%q thumb=%q err=%q",
				tc.Name, result.URL, result.Thumb, gotErr, tc.Want.URL, tc.Want.Thumb, tc.Want.Error)
		}
	}
}

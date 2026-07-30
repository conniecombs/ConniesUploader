package core

import (
	"context"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestSuccessCheckAnyAllowsRedirectedThreadURL(t *testing.T) {
	values := map[string]string{
		"__response_body__": "Bondage Cafe thread page",
		"__final_url__":     "https://vipergirls.to/threads/16296281-Bondage-Cafe?p=263900000#post263900000",
	}
	check := &SuccessCheck{
		Type: "any",
		Any: []SuccessCheck{
			{Field: "__response_body__", Match: "thank you for posting", Type: "contains"},
			{Field: "__final_url__", Match: `(?i)(?:/threads/\d+|showthread\.php\?t=\d+)`, Type: "regex"},
		},
	}

	if err := checkSuccess(check, values); err != nil {
		t.Fatalf("checkSuccess returned error: %v", err)
	}
}

func TestSuccessCheckAnyFailsWhenNoConditionMatches(t *testing.T) {
	values := map[string]string{
		"__response_body__": "The following errors occurred with your submission.",
		"__final_url__":     "https://vipergirls.to/newreply.php?do=postreply&t=16296281",
	}
	check := &SuccessCheck{
		Type: "any",
		Any: []SuccessCheck{
			{Field: "__response_body__", Match: "thank you for posting", Type: "contains"},
			{Field: "__final_url__", Match: `(?i)(?:/threads/\d+|showthread\.php\?t=\d+)`, Type: "regex"},
		},
	}

	if err := checkSuccess(check, values); err == nil {
		t.Fatal("checkSuccess succeeded unexpectedly")
	}
}

func TestExecuteGenericRequestStoresFinalURLForSuccessCheck(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/submit":
			http.Redirect(w, r, "/threads/12345-title?p=678#post678", http.StatusFound)
		case "/threads/12345-title":
			_, _ = w.Write([]byte("posted thread page"))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	spec := &GenericHttpRequestSpec{
		URL:          server.URL + "/submit",
		Method:       http.MethodPost,
		ResponseType: "html",
		SuccessCheck: &SuccessCheck{
			Field: "__final_url__",
			Match: `/threads/12345-title`,
			Type:  "regex",
		},
	}

	extracted, err := ExecuteGenericRequest(context.Background(), server.Client(), spec, nil)
	if err != nil {
		t.Fatalf("ExecuteGenericRequest returned error: %v", err)
	}
	if got := extracted["__final_url__"]; got != server.URL+"/threads/12345-title?p=678#post678" {
		t.Fatalf("__final_url__ = %q", got)
	}
}

func TestExecuteGenericRequestPreRequestReusesBaseCookieJar(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/login":
			http.SetCookie(w, &http.Cookie{Name: "auth", Value: "ok"})
			_, _ = w.Write([]byte("logged in"))
		case "/reply-form":
			cookie, err := r.Cookie("auth")
			if err != nil || cookie.Value != "ok" {
				_, _ = w.Write([]byte(`<input name="securitytoken" value="guest">`))
				return
			}
			_, _ = w.Write([]byte(`<input name="securitytoken" value="tok">`))
		case "/submit":
			cookie, err := r.Cookie("auth")
			if err != nil || cookie.Value != "ok" {
				_, _ = w.Write([]byte("not logged in"))
				return
			}
			if got := r.FormValue("securitytoken"); got != "tok" {
				_, _ = w.Write([]byte("bad token"))
				return
			}
			http.Redirect(w, r, "/threads/12345-title?p=678#post678", http.StatusFound)
		case "/threads/12345-title":
			_, _ = w.Write([]byte("posted thread page"))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	jar, err := cookiejar.New(nil)
	if err != nil {
		t.Fatalf("cookiejar.New failed: %v", err)
	}
	client := server.Client()
	client.Jar = jar

	_, err = ExecuteGenericRequest(context.Background(), client, &GenericHttpRequestSpec{
		URL:          server.URL + "/login",
		Method:       http.MethodGet,
		UseCookies:   true,
		ResponseType: "html",
	}, nil)
	if err != nil {
		t.Fatalf("login request returned error: %v", err)
	}

	_, err = ExecuteGenericRequest(context.Background(), client, &GenericHttpRequestSpec{
		URL:          server.URL + "/submit",
		Method:       http.MethodPost,
		UseCookies:   true,
		ResponseType: "html",
		FormFields: map[string]string{
			"securitytoken": "{security_token}",
		},
		PreRequest: &PreRequestSpec{
			URL:          server.URL + "/reply-form",
			Method:       http.MethodGet,
			UseCookies:   true,
			ResponseType: "html",
			ExtractFields: map[string]string{
				"security_token": "input[name='securitytoken']",
			},
		},
		SuccessCheck: &SuccessCheck{
			Field: "__final_url__",
			Match: `/threads/12345-title`,
			Type:  "regex",
		},
	}, nil)
	if err != nil {
		t.Fatalf("post request returned error: %v", err)
	}
}

func TestUploadClientWithPreRequestCookiesPreservesBaseUploadSettings(t *testing.T) {
	baseJar, err := cookiejar.New(nil)
	if err != nil {
		t.Fatalf("cookiejar.New failed: %v", err)
	}
	sessionJar, err := cookiejar.New(nil)
	if err != nil {
		t.Fatalf("cookiejar.New failed: %v", err)
	}
	baseTransport := &http.Transport{}
	base := &http.Client{
		Timeout:   3 * time.Minute,
		Jar:       baseJar,
		Transport: baseTransport,
	}
	preClient := &http.Client{
		Timeout: PreRequestTimeout,
		Jar:     sessionJar,
	}

	uploadClient := uploadClientWithPreRequestCookies(base, preClient)

	if uploadClient == preClient {
		t.Fatal("upload client reused the pre-request client")
	}
	if uploadClient.Timeout != base.Timeout {
		t.Fatalf("upload timeout = %v, want base timeout %v", uploadClient.Timeout, base.Timeout)
	}
	if uploadClient.Jar != sessionJar {
		t.Fatal("upload client did not preserve the authenticated pre-request cookie jar")
	}
	if uploadClient.Transport != baseTransport {
		t.Fatal("upload client did not preserve the base upload transport")
	}
}

func TestUploadPreRequestClientUsesIsolatedCookieJar(t *testing.T) {
	baseJar, err := cookiejar.New(nil)
	if err != nil {
		t.Fatalf("cookiejar.New failed: %v", err)
	}
	baseTransport := &http.Transport{}
	base := &http.Client{
		Timeout:   3 * time.Minute,
		Jar:       baseJar,
		Transport: baseTransport,
	}

	preClient := isolatedPreRequestClient(base, true)

	if preClient == base {
		t.Fatal("pre-request client reused the base client")
	}
	if preClient.Jar == nil {
		t.Fatal("pre-request client did not get a cookie jar")
	}
	if preClient.Jar == baseJar {
		t.Fatal("pre-request client reused the shared base cookie jar")
	}
	if preClient.Transport != baseTransport {
		t.Fatal("pre-request client did not preserve the base transport")
	}
}

func TestExecuteGenericRequestOptionalPreRequestFieldSubstitutesEmptyValue(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/reply-form":
			_, _ = w.Write([]byte(`
				<input name="securitytoken" value="tok">
				<input name="posthash" value="hash">
			`))
		case "/submit":
			if err := r.ParseForm(); err != nil {
				t.Fatalf("ParseForm failed: %v", err)
			}
			if got := r.FormValue("securitytoken"); got != "tok" {
				t.Fatalf("securitytoken = %q", got)
			}
			if got := r.FormValue("posthash"); got != "hash" {
				t.Fatalf("posthash = %q", got)
			}
			if _, ok := r.Form["multiquoteempty"]; !ok {
				t.Fatal("multiquoteempty form key was not submitted")
			}
			if got := r.FormValue("multiquoteempty"); got != "" {
				t.Fatalf("multiquoteempty = %q", got)
			}
			_, _ = w.Write([]byte("thank you for posting"))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	_, err := ExecuteGenericRequest(context.Background(), server.Client(), &GenericHttpRequestSpec{
		URL:          server.URL + "/submit",
		Method:       http.MethodPost,
		ResponseType: "html",
		FormFields: map[string]string{
			"securitytoken":   "{security_token}",
			"posthash":        "{posthash}",
			"multiquoteempty": "{multiquoteempty}",
		},
		PreRequest: &PreRequestSpec{
			URL:          server.URL + "/reply-form",
			Method:       http.MethodGet,
			ResponseType: "html",
			ExtractFields: map[string]string{
				"security_token":    "input[name='securitytoken']",
				"posthash":          "input[name='posthash']",
				"multiquoteempty?":  "input[name='multiquoteempty']",
				"missing_required?": "input[name='also_missing']",
				"another_optional?": "input[name='still_missing']",
			},
		},
		SuccessCheck: &SuccessCheck{
			Field: "__response_body__",
			Match: "thank you for posting",
			Type:  "contains",
		},
	}, nil)
	if err != nil {
		t.Fatalf("ExecuteGenericRequest returned error: %v", err)
	}
}

func TestExecuteGenericRequestFieldExtractionErrorIncludesSanitizedDiagnostics(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`
			<html>
				<head><title>Reply Form</title></head>
				<body>
					<form method="post" action="/submit">
						<input name="securitytoken" value="secret-token">
						<textarea name="message"></textarea>
					</form>
				</body>
			</html>
		`))
	}))
	defer server.Close()

	_, err := ExecuteGenericRequest(context.Background(), server.Client(), &GenericHttpRequestSpec{
		URL:          server.URL + "/reply-form",
		Method:       http.MethodGet,
		ResponseType: "html",
		ExtractFields: map[string]string{
			"missing": "input[name='missing']",
		},
	}, nil)
	if err == nil {
		t.Fatal("ExecuteGenericRequest returned nil error")
	}
	msg := err.Error()
	for _, want := range []string{
		"diagnostics:",
		"status=200",
		"Reply Form",
		"action=\"/submit\"",
		"fields=\"securitytoken,message\"",
	} {
		if !strings.Contains(msg, want) {
			t.Fatalf("error %q did not contain %q", msg, want)
		}
	}
	if strings.Contains(msg, "secret-token") {
		t.Fatalf("error leaked form value: %q", msg)
	}
}

package core

import (
	"context"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"testing"
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

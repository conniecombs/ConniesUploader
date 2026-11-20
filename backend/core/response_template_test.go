// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import "testing"

func TestThumbTemplateCanBuildOnTheParsedLink(t *testing.T) {
	cases := []struct {
		link, template, want string
	}{
		{"https://i.example/AbCd123.jpg", "{url_no_ext}m{url_dot_ext}", "https://i.example/AbCd123m.jpg"},
		{"https://i.example/a/AbCd123.png?x=1#f", "{url_no_ext}t{url_dot_ext}", "https://i.example/a/AbCd123t.png"},
		{"https://i.example/AbCd123", "{url_no_ext}h{url_dot_ext}", "https://i.example/AbCd123h"},
	}
	for _, tc := range cases {
		body := []byte(`{"success":true,"data":{"id":"AbCd123","link":"` + tc.link + `"}}`)
		urlStr, thumbStr, err := parseHttpResponseBody(body, &ResponseParserSpec{
			Type:          "json",
			URLPath:       "data.link",
			StatusPath:    "success",
			SuccessValue:  "true",
			ThumbTemplate: tc.template,
		}, "/in/photo.jpeg")
		if err != nil {
			t.Fatalf("%s: %v", tc.link, err)
		}
		if urlStr != tc.link || thumbStr != tc.want {
			t.Fatalf("%s: url=%q thumb=%q, want thumb %q", tc.link, urlStr, thumbStr, tc.want)
		}
	}
}

func TestThumbTemplateURLPartsInHTMLParser(t *testing.T) {
	body := []byte(`<input id="link" value="https://img.example/v/xyz.gif">`)
	_, thumbStr, err := parseHttpResponseBody(body, &ResponseParserSpec{
		Type:          "html",
		URLPath:       "input#link",
		ThumbTemplate: "{url_no_ext}_t{url_dot_ext}",
	}, "/in/a.gif")
	if err != nil {
		t.Fatal(err)
	}
	if thumbStr != "https://img.example/v/xyz_t.gif" {
		t.Fatalf("thumb = %q", thumbStr)
	}
}

func TestURLNoExtKeepsTheLinksEscaping(t *testing.T) {
	cases := []struct {
		link, wantNoExt, wantExt string
	}{
		{"https://i.example/a%2Fb/AbC.jpg", "https://i.example/a%2Fb/AbC", ".jpg"},
		{"https://i.example/a%2fb/AbC.jpg?x=1#f", "https://i.example/a%2fb/AbC", ".jpg"},
		{"https://i.example/it's(1)!*.png", "https://i.example/it's(1)!*", ".png"},
		{"https://i.example/a%20b.gif", "https://i.example/a%20b", ".gif"},
		{"https://i.example/AbC", "https://i.example/AbC", ""},
	}
	for _, tc := range cases {
		noExt, ext := splitURLExtension(tc.link)
		if noExt != tc.wantNoExt || ext != tc.wantExt {
			t.Errorf("%s: got (%q, %q), want (%q, %q)", tc.link, noExt, ext, tc.wantNoExt, tc.wantExt)
		}
	}
}

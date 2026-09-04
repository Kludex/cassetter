package cassetter_test

import (
	"net/http"
	"strconv"
	"strings"
	"testing"

	"github.com/Kludex/cassetter/go"
)

func TestScrubFiltersSecretsBeforeSave(t *testing.T) {
	t.Parallel()
	cassette := &cassetter.Cassette{
		Version: 1,
		Interactions: []cassetter.HTTPInteraction{{
			Request: cassetter.HTTPRequest{
				Method:  http.MethodPost,
				URI:     "https://example.com/login?api_key=secret&keep=1#access_token=token",
				Headers: http.Header{"Authorization": {"Bearer secret"}, "Accept": {"application/json"}},
				Body: cassetter.Body{
					Type: cassetter.BodyTypeJSON,
					Content: map[string]any{
						"password": "hunter2",
						"nested":   map[string]any{"refresh_token": "token", "keep": true},
						"typed":    map[string]string{"client_secret": "secret"},
					},
				},
			},
			Response: cassetter.HTTPResponse{
				Status:  http.StatusOK,
				Headers: http.Header{"Set-Cookie": {"session=secret"}, "Content-Length": {"99"}},
				Body: cassetter.Body{
					Type:    cassetter.BodyTypeText,
					Content: "data: {\"access_token\":\"token\",\"keep\":true}\n\n",
				},
			},
		}, {
			Request: cassetter.HTTPRequest{Method: http.MethodGet, URI: "https://example.com/text"},
			Response: cassetter.HTTPResponse{
				Status: http.StatusOK,
				Body: cassetter.Body{
					Type:    cassetter.BodyTypeText,
					Content: `prefix {"password":"tail-secret"} suffix`,
				},
			},
		}},
	}
	cassette.Scrub(cassetter.DefaultSecurityConfig())
	interaction := cassette.Interactions[0]
	if interaction.Request.Headers.Get("Authorization") != "" {
		t.Fatal("authorization header was not removed")
	}
	if interaction.Response.Headers.Get("Set-Cookie") != "" {
		t.Fatal("set-cookie header was not removed")
	}
	if interaction.Request.URI != "https://example.com/login?api_key=[FILTERED]&keep=1#access_token=[FILTERED]" {
		t.Fatalf("URI = %q", interaction.Request.URI)
	}
	requestBody := interaction.Request.Body.Content.(map[string]any)
	if requestBody["password"] != "[FILTERED]" {
		t.Fatalf("password = %v", requestBody["password"])
	}
	typed := requestBody["typed"].(map[string]any)
	if typed["client_secret"] != "[FILTERED]" {
		t.Fatalf("client secret = %v", typed["client_secret"])
	}
	responseBody := interaction.Response.Body.Content.(string)
	if responseBody != "data: {\"access_token\":\"[FILTERED]\",\"keep\":true}\n\n" {
		t.Fatalf("response body = %q", responseBody)
	}
	if interaction.Response.Headers.Get("Content-Length") != strconv.Itoa(len(responseBody)) {
		t.Fatalf("content length = %q", interaction.Response.Headers.Get("Content-Length"))
	}
	unstructured := cassette.Interactions[1].Response.Body.Content.(string)
	if strings.Contains(unstructured, "tail-secret") {
		t.Fatalf("unstructured secret was not filtered: %q", unstructured)
	}
}

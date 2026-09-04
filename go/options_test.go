package cassetter_test

import (
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"github.com/Kludex/cassetter/go"
)

func TestTransportExtendsSecurityDefaults(t *testing.T) {
	t.Parallel()
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		writer.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(writer, `{"private_key":"secret"}`)
	}))
	defer server.Close()
	path := filepath.Join(t.TempDir(), "custom.yaml")
	client := &http.Client{Transport: cassetter.NewTransport(
		nil,
		cassetter.WithPath(path),
		cassetter.WithFilterHeaders("x-company-token", "X-Company-Token"),
		cassetter.WithFilterQueryParameters("signature"),
		cassetter.WithBodyScrubPatterns("private_key"),
		cassetter.WithFilterReplacement("***"),
	)}
	request, err := http.NewRequest(http.MethodGet, server.URL+"?signature=secret&keep=1", nil)
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Authorization", "Bearer secret")
	request.Header.Set("X-Company-Token", "secret")
	response, err := client.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := io.Copy(io.Discard, response.Body); err != nil {
		t.Fatal(err)
	}
	if err := response.Body.Close(); err != nil {
		t.Fatal(err)
	}
	cassette, err := cassetter.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	interaction := cassette.Interactions[0]
	if interaction.Request.Headers.Get("authorization") != "" {
		t.Fatal("default header was not removed")
	}
	if interaction.Request.Headers.Get("x-company-token") != "" {
		t.Fatal("custom header was not removed")
	}
	if interaction.Request.URI != server.URL+"?signature=***&keep=1" {
		t.Fatalf("URI = %q", interaction.Request.URI)
	}
	content := interaction.Response.Body.Content.(map[string]any)
	if content["private_key"] != "***" {
		t.Fatalf("private key = %v", content["private_key"])
	}
}

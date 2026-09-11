package cassetter_test

import (
	"errors"
	"io"
	"net/http"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Kludex/cassetter/go"
)

const usersURI = "https://example.com/users"

func TestTransportAppliesDefaultCassetteExtension(t *testing.T) {
	t.Parallel()
	directory := t.TempDir()
	saveMatchingCassette(t, filepath.Join(directory, "users.yaml"), cassetter.HTTPRequest{
		Method: http.MethodGet,
		URI:    usersURI,
	})
	assertReplaysUsers(t, cassetter.WithPath(filepath.Join(directory, "users")))
}

func TestTransportCassetteExtensionSelectsTOML(t *testing.T) {
	t.Parallel()
	directory := t.TempDir()
	stem := filepath.Join(directory, "users")
	tomlPath := stem + ".toml"
	transport := cassetter.NewTransport(
		roundTripFunc(func(request *http.Request) (*http.Response, error) {
			return &http.Response{
				StatusCode:    http.StatusOK,
				Header:        make(http.Header),
				Body:          io.NopCloser(strings.NewReader("ok")),
				ContentLength: 2,
				Request:       request,
			}, nil
		}),
		cassetter.WithPath(stem),
		cassetter.WithCassetteExtension("toml"),
		cassetter.WithRecordMode(cassetter.RecordModeAll),
	)
	client := &http.Client{Transport: transport}
	response, err := client.Get("https://example.com/users")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := io.Copy(io.Discard, response.Body); err != nil {
		t.Fatal(err)
	}
	if err := response.Body.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := cassetter.Load(tomlPath); err != nil {
		t.Fatalf("expected toml cassette: %v", err)
	}
}

func TestTransportCassetteExtensionKeepsExplicitSuffix(t *testing.T) {
	t.Parallel()
	directory := t.TempDir()
	yamlPath := filepath.Join(directory, "users.yaml")
	saveMatchingCassette(t, yamlPath, cassetter.HTTPRequest{
		Method: http.MethodGet,
		URI:    usersURI,
	})
	assertReplaysUsers(t,
		cassetter.WithPath(yamlPath),
		cassetter.WithCassetteExtension("toml"),
	)
}

func TestTransportCassetteExtensionRejectsUnknownValues(t *testing.T) {
	t.Parallel()
	transport := cassetter.NewTransport(
		nil,
		cassetter.WithPath(filepath.Join(t.TempDir(), "users")),
		cassetter.WithCassetteExtension("json"),
	)
	if err := transport.Initialize(); err == nil || !strings.Contains(err.Error(), "cassette_extension") {
		t.Fatalf("initialization error = %v", err)
	}
}

func assertReplaysUsers(t *testing.T, options ...cassetter.Option) {
	t.Helper()
	options = append([]cassetter.Option{cassetter.WithRecordMode(cassetter.RecordModeNone)}, options...)
	client := &http.Client{Transport: cassetter.NewTransport(
		roundTripFunc(func(*http.Request) (*http.Response, error) {
			return nil, errors.New("unexpected live request")
		}),
		options...,
	)}
	response, err := client.Get(usersURI)
	if err != nil {
		t.Fatal(err)
	}
	content, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	if err := response.Body.Close(); err != nil {
		t.Fatal(err)
	}
	if string(content) != "matched" {
		t.Fatalf("replay body = %q", content)
	}
}

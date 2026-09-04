package cassetter_test

import (
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Kludex/cassetter/go"
)

func TestNewTestTransportInitializesRewrite(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	if err := os.WriteFile(path, []byte("version: 1\ninteractions: []\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	cassetter.NewTestTransport(
		t,
		roundTripFunc(func(*http.Request) (*http.Response, error) {
			return nil, errors.New("unexpected request")
		}),
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeRewrite),
	)
	if _, err := os.Stat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("rewrite cassette still exists: %v", err)
	}
}

func TestTransportInitializeReportsConfigurationFailure(t *testing.T) {
	t.Parallel()
	transport := cassetter.NewTransport(nil)
	if err := transport.Initialize(); err == nil || !strings.Contains(err.Error(), "cassette path") {
		t.Fatalf("initialization error = %v", err)
	}
}

func TestTransportCloseReportsIncompleteResponse(t *testing.T) {
	t.Parallel()
	transport := cassetter.NewTransport(
		responseTransport("unfinished", -1),
		cassetter.WithPath(filepath.Join(t.TempDir(), "cassette.yaml")),
	)
	client := &http.Client{Transport: transport}
	response, err := client.Get("https://example.com/stream")
	if err != nil {
		t.Fatal(err)
	}
	buffer := make([]byte, 1)
	if _, err := response.Body.Read(buffer); err != nil {
		t.Fatal(err)
	}
	closeErr := transport.Close()
	if !errors.Is(closeErr, cassetter.ErrIncompleteRecording) ||
		!strings.Contains(closeErr.Error(), "GET https://example.com/stream") {
		t.Fatalf("close error = %v", closeErr)
	}
	if err := response.Body.Close(); err != nil {
		t.Fatal(err)
	}
	request, err := http.NewRequest(http.MethodGet, "https://example.com/after-close", nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := transport.RoundTrip(request); !errors.Is(err, cassetter.ErrTransportClosed) {
		t.Fatalf("request after close error = %v", err)
	}
}

func TestTransportCloseReportsSaveFailure(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	transport := cassetter.NewTransport(responseTransport("complete", 8), cassetter.WithPath(path))
	if err := transport.Initialize(); err != nil {
		t.Fatal(err)
	}
	response, err := (&http.Client{Transport: transport}).Get("https://example.com/value")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(path, 0o700); err != nil {
		t.Fatal(err)
	}
	if _, err := io.ReadAll(response.Body); err == nil {
		t.Fatal("reading the response did not report the save failure")
	}
	_ = response.Body.Close()
	if err := transport.Close(); err == nil || !strings.Contains(err.Error(), "replace cassette") {
		t.Fatalf("close error = %v", err)
	}
}

func TestTransportCloseReportsEmptyAllSaveFailure(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	if err := os.WriteFile(path, []byte("version: 1\ninteractions: []\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	transport := cassetter.NewTransport(
		nil,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeAll),
	)
	if err := transport.Initialize(); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(path, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := transport.Close(); err == nil || !strings.Contains(err.Error(), "replace cassette") {
		t.Fatalf("close error = %v", err)
	}
}

func TestNewTestTransportCompletesCleanly(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	transport := cassetter.NewTestTransport(t, responseTransport("complete", 8), cassetter.WithPath(path))
	response, err := (&http.Client{Transport: transport}).Get("https://example.com/value")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := io.Copy(io.Discard, response.Body); err != nil {
		t.Fatal(err)
	}
	if err := response.Body.Close(); err != nil {
		t.Fatal(err)
	}
	if err := transport.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := cassetter.Load(path); err != nil {
		t.Fatal(err)
	}
}

func responseTransport(content string, contentLength int64) http.RoundTripper {
	return roundTripFunc(func(request *http.Request) (*http.Response, error) {
		return &http.Response{
			StatusCode:    http.StatusOK,
			Header:        make(http.Header),
			Body:          io.NopCloser(strings.NewReader(content)),
			ContentLength: contentLength,
			Request:       request,
		}, nil
	})
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (function roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return function(request)
}

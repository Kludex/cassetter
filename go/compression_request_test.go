package cassetter_test

import (
	"bytes"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"github.com/Kludex/cassetter/go"
)

func TestTransportDecompressesRequestsBeforeScrubbing(t *testing.T) {
	t.Parallel()
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if _, err := io.Copy(io.Discard, request.Body); err != nil {
			t.Errorf("read request: %v", err)
		}
		writer.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	path := filepath.Join(t.TempDir(), "compressed-request.yaml")
	content := compressGzip(t, []byte(`{"password":"secret","ok":true}`))
	request, err := http.NewRequest(http.MethodPost, server.URL, bytes.NewReader(content))
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Content-Encoding", "gzip")
	request.Header.Set("Content-Type", "application/json")
	client := &http.Client{Transport: cassetter.NewTransport(nil, cassetter.WithPath(path))}
	response, err := client.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	if err := response.Body.Close(); err != nil {
		t.Fatal(err)
	}

	cassette, err := cassetter.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	recorded := cassette.Interactions[0].Request
	if recorded.Headers.Get("Content-Encoding") != "" {
		t.Fatal("content-encoding was recorded")
	}
	body := recorded.Body.Content.(map[string]any)
	if body["password"] != "[FILTERED]" {
		t.Fatalf("password = %v", body["password"])
	}
}

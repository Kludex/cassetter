package cassetter_test

import (
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"github.com/Kludex/cassetter/go"
)

func TestTransportDoesNotCommitFailedSaves(t *testing.T) {
	t.Parallel()
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		_, _ = io.WriteString(writer, request.URL.Path)
	}))
	defer server.Close()
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	client := &http.Client{Transport: cassetter.NewTransport(nil, cassetter.WithPath(path))}

	response, err := client.Get(server.URL + "/failed")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(path, 0o700); err != nil {
		t.Fatal(err)
	}
	if _, err := io.ReadAll(response.Body); err == nil {
		t.Fatal("recording succeeded with a directory at the cassette path")
	}
	if err := response.Body.Close(); err == nil {
		t.Fatal("Close did not report the failed save")
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}

	response, err = client.Get(server.URL + "/saved")
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
	if len(cassette.Interactions) != 1 || cassette.Interactions[0].Request.URI != server.URL+"/saved" {
		t.Fatalf("interactions = %#v", cassette.Interactions)
	}
}

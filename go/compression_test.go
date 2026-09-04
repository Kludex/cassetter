package cassetter_test

import (
	"bytes"
	"compress/flate"
	"compress/gzip"
	"compress/zlib"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strconv"
	"testing"

	"github.com/Kludex/cassetter/go"
	"github.com/andybalholm/brotli"
	"github.com/klauspost/compress/zstd"
)

func TestTransportDecompressesResponsesBeforeScrubbing(t *testing.T) {
	t.Parallel()
	original := []byte(`{"access_token":"secret","ok":true}`)
	encodings := map[string][]byte{
		"br":          compressBrotli(t, original),
		"deflate":     compressZlib(t, original),
		"deflate-raw": compressDeflate(t, original),
		"gzip":        compressGzip(t, original),
		"zstd":        compressZstd(t, original),
	}
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		encoding := request.URL.Path[1:]
		content := encodings[encoding]
		if encoding == "deflate-raw" {
			encoding = "deflate"
		}
		writer.Header().Set("Content-Encoding", encoding)
		writer.Header().Set("Content-Length", strconv.Itoa(len(content)))
		writer.Header().Set("Content-Type", "application/json")
		_, _ = writer.Write(content)
	}))
	defer server.Close()

	path := filepath.Join(t.TempDir(), "compressed.yaml")
	client := &http.Client{Transport: cassetter.NewTransport(nil, cassetter.WithPath(path))}
	for encoding, expected := range encodings {
		request, err := http.NewRequest(http.MethodGet, server.URL+"/"+encoding, nil)
		if err != nil {
			t.Fatal(err)
		}
		request.Header.Set("Accept-Encoding", encoding)
		response, err := client.Do(request)
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
		if !bytes.Equal(content, expected) {
			t.Fatalf("%s response was changed before reaching the caller", encoding)
		}
	}

	cassette, err := cassetter.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(cassette.Interactions) != len(encodings) {
		t.Fatalf("interactions = %d", len(cassette.Interactions))
	}
	for _, interaction := range cassette.Interactions {
		if interaction.Response.Headers.Get("Content-Encoding") != "" {
			t.Fatal("content-encoding was recorded")
		}
		content := interaction.Response.Body.Content.(map[string]any)
		if content["access_token"] != "[FILTERED]" {
			t.Fatalf("access token = %v", content["access_token"])
		}
		encoded, err := json.Marshal(content)
		if err != nil {
			t.Fatal(err)
		}
		length := interaction.Response.Headers.Get("Content-Length")
		if length != "" && length != strconv.Itoa(len(encoded)) {
			t.Fatalf("content length = %q", length)
		}
	}
}

func compressGzip(t *testing.T, content []byte) []byte {
	t.Helper()
	var target bytes.Buffer
	writer := gzip.NewWriter(&target)
	writeCompressed(t, writer, content)
	return target.Bytes()
}

func compressZlib(t *testing.T, content []byte) []byte {
	t.Helper()
	var target bytes.Buffer
	writer := zlib.NewWriter(&target)
	writeCompressed(t, writer, content)
	return target.Bytes()
}

func compressDeflate(t *testing.T, content []byte) []byte {
	t.Helper()
	var target bytes.Buffer
	writer, err := flate.NewWriter(&target, flate.DefaultCompression)
	if err != nil {
		t.Fatal(err)
	}
	writeCompressed(t, writer, content)
	return target.Bytes()
}

func compressBrotli(t *testing.T, content []byte) []byte {
	t.Helper()
	var target bytes.Buffer
	writer := brotli.NewWriter(&target)
	writeCompressed(t, writer, content)
	return target.Bytes()
}

func compressZstd(t *testing.T, content []byte) []byte {
	t.Helper()
	var target bytes.Buffer
	writer, err := zstd.NewWriter(&target)
	if err != nil {
		t.Fatal(err)
	}
	writeCompressed(t, writer, content)
	return target.Bytes()
}

func writeCompressed(t *testing.T, writer io.WriteCloser, content []byte) {
	t.Helper()
	if _, err := writer.Write(content); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
}

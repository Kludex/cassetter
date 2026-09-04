package cassetter_test

import (
	"fmt"
	"io"
	"net/http"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Kludex/cassetter/go"
)

func TestTransportNormalizesRecordedTextToNFC(t *testing.T) {
	t.Parallel()
	base := roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if _, err := io.Copy(io.Discard, request.Body); err != nil {
			return nil, err
		}
		content := "cafe\u0301"
		return &http.Response{
			StatusCode:    http.StatusOK,
			Header:        http.Header{"Content-Type": {"text/plain"}},
			Body:          io.NopCloser(strings.NewReader(content)),
			ContentLength: int64(len(content)),
			Request:       request,
		}, nil
	})
	path := filepath.Join(t.TempDir(), "unicode.yaml")
	transport := cassetter.NewTransport(base, cassetter.WithPath(path))
	request, err := http.NewRequest(
		http.MethodPost,
		"https://example.com/unicode",
		strings.NewReader("{\"name\":\"cafe\u0301\",\"id\":9007199254740993}"),
	)
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := (&http.Client{Transport: transport}).Do(request)
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
	requestContent := interaction.Request.Body.Content.(map[string]any)
	if requestContent["name"] != "café" || fmt.Sprint(requestContent["id"]) != "9007199254740993" {
		t.Fatalf("request body = %#v", requestContent)
	}
	if interaction.Response.Body.Content != "café" {
		t.Fatalf("response body = %#v", interaction.Response.Body.Content)
	}
}

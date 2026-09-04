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

func TestCassetteNormalizesLoadedBodiesToNFC(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	cassette := &cassetter.Cassette{
		Version: 1,
		Interactions: []cassetter.HTTPInteraction{{
			Request: cassetter.HTTPRequest{
				Method: http.MethodPost,
				URI:    "https://example.com",
				Body: cassetter.Body{Type: cassetter.BodyTypeJSON, Content: map[string]any{
					"cafe\u0301": "cafe\u0301",
				}},
			},
			Response: cassetter.HTTPResponse{
				Status: http.StatusOK,
				Body:   cassetter.Body{Type: cassetter.BodyTypeText, Content: "cafe\u0301"},
			},
		}},
	}
	if err := cassette.Save(path); err != nil {
		t.Fatal(err)
	}
	loaded, err := cassetter.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	content := loaded.Interactions[0].Request.Body.Content.(map[string]any)
	if content["café"] != "café" {
		t.Fatalf("loaded request body = %#v", content)
	}
	if loaded.Interactions[0].Response.Body.Content != "café" {
		t.Fatalf("loaded response body = %#v", loaded.Interactions[0].Response.Body)
	}
}

func TestCassetteRejectsNormalizedJSONKeyCollisions(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	cassette := &cassetter.Cassette{
		Version: 1,
		Interactions: []cassetter.HTTPInteraction{{
			Request: cassetter.HTTPRequest{
				Method: http.MethodPost,
				URI:    "https://example.com",
				Body: cassetter.Body{Type: cassetter.BodyTypeJSON, Content: map[string]any{
					"é":       1,
					"e\u0301": 2,
				}},
			},
			Response: cassetter.HTTPResponse{Status: http.StatusOK},
		}},
	}
	if err := cassette.Save(path); err != nil {
		t.Fatal(err)
	}
	if _, err := cassetter.Load(path); err == nil || !strings.Contains(err.Error(), "normalize") {
		t.Fatalf("load error = %v", err)
	}
}

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
	hugeInteger := strings.Repeat("9", 400)
	payload := fmt.Sprintf(
		`{"cafe\u0301":"cafe\u0301","name":"cafe\u0301","id":18446744073709551616,"huge":%s,"exponent":1e1000}`,
		hugeInteger,
	)
	request, err := http.NewRequest(http.MethodPost, "https://example.com/unicode", strings.NewReader(payload))
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
	if requestContent["name"] != "café" || requestContent["café"] != "café" ||
		fmt.Sprint(requestContent["id"]) != "18446744073709551616" ||
		fmt.Sprint(requestContent["huge"]) != hugeInteger || fmt.Sprint(requestContent["exponent"]) != "1e1000" {
		t.Fatalf("request body = %#v", requestContent)
	}
	if interaction.Response.Body.Content != "café" {
		t.Fatalf("response body = %#v", interaction.Response.Body.Content)
	}
}

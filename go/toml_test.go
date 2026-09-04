package cassetter_test

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Kludex/cassetter/go"
)

func TestCassetteRoundTripsTOML(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.TOML")
	cassette := &cassetter.Cassette{
		Version: 1,
		Interactions: []cassetter.HTTPInteraction{
			{
				Request: cassetter.HTTPRequest{
					Method:  http.MethodPost,
					URI:     "https://example.com/json",
					Headers: http.Header{"X-Multi": {"one", "two"}},
					Body: cassetter.Body{Type: cassetter.BodyTypeJSON, Content: map[string]any{
						"id": json.Number("18446744073709551616"), "items": []any{"one", nil, true},
					}},
				},
				Response: cassetter.HTTPResponse{
					Status: http.StatusOK,
					Body:   cassetter.Body{Type: cassetter.BodyTypeText, Content: "café"},
				},
				RecordedAt: "2026-01-02T03:04:05Z",
			},
			{
				Request: cassetter.HTTPRequest{
					Method: http.MethodGet,
					URI:    "https://example.com/binary",
					Body:   cassetter.Body{Type: cassetter.BodyTypeBinary, Content: []byte{0, 1, 255}},
				},
				Response: cassetter.HTTPResponse{Status: http.StatusNoContent},
			},
		},
	}
	if err := cassette.Save(path); err != nil {
		t.Fatal(err)
	}
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(content, []byte(`body_content = '{"id":18446744073709551616`)) ||
		!bytes.Contains(content, []byte(`body_content = '0001ff'`)) {
		t.Fatalf("TOML content =\n%s", content)
	}
	loaded, err := cassetter.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(loaded.Interactions) != 2 || loaded.Interactions[0].RecordedAt != "2026-01-02T03:04:05Z" {
		t.Fatalf("interactions = %#v", loaded.Interactions)
	}
	jsonBody := loaded.Interactions[0].Request.Body.Content.(map[string]any)
	if fmt.Sprint(jsonBody["id"]) != "18446744073709551616" || len(jsonBody["items"].([]any)) != 3 {
		t.Fatalf("JSON body = %#v", jsonBody)
	}
	if values := loaded.Interactions[0].Request.Headers.Values("X-Multi"); strings.Join(values, ",") != "one,two" {
		t.Fatalf("header values = %v", values)
	}
	if loaded.Interactions[0].Response.Body.Content != "café" {
		t.Fatalf("text body = %#v", loaded.Interactions[0].Response.Body)
	}
	binary := loaded.Interactions[1].Request.Body.Content.([]byte)
	if !bytes.Equal(binary, []byte{0, 1, 255}) {
		t.Fatalf("binary body = %v", binary)
	}
}

func TestCassettePreservesJSONNullAndDecimal(t *testing.T) {
	t.Parallel()
	for _, extension := range []string{".yaml", ".toml"} {
		extension := extension
		t.Run(extension, func(t *testing.T) {
			t.Parallel()
			path := filepath.Join(t.TempDir(), "cassette"+extension)
			cassette := &cassetter.Cassette{
				Version: 1,
				Interactions: []cassetter.HTTPInteraction{{
					Request: cassetter.HTTPRequest{
						Method: http.MethodPost,
						URI:    "https://example.com",
						Body:   cassetter.Body{Type: cassetter.BodyTypeJSON, Content: nil},
					},
					Response: cassetter.HTTPResponse{
						Status: http.StatusOK,
						Body: cassetter.Body{Type: cassetter.BodyTypeJSON, Content: map[string]any{
							"value": json.Number("0.123456789012345678901"),
						}},
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
			if body := loaded.Interactions[0].Request.Body; body.Type != cassetter.BodyTypeJSON || body.Content != nil {
				t.Fatalf("null body = %#v", body)
			}
			value := loaded.Interactions[0].Response.Body.Content.(map[string]any)["value"]
			if fmt.Sprint(value) != "0.123456789012345678901" {
				t.Fatalf("decimal = %v", value)
			}
		})
	}
}

func TestTransportRecordsAndReplaysTOML(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.toml")
	transport := cassetter.NewTransport(responseTransport("recorded", 8), cassetter.WithPath(path))
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
	replay := cassetter.NewTransport(
		nil,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
	)
	replayed, err := (&http.Client{Transport: replay}).Get("https://example.com/value")
	if err != nil {
		t.Fatal(err)
	}
	content, err := io.ReadAll(replayed.Body)
	if err != nil {
		t.Fatal(err)
	}
	if err := replayed.Body.Close(); err != nil {
		t.Fatal(err)
	}
	if string(content) != "recorded" {
		t.Fatalf("replayed body = %q", content)
	}
}

func TestCassetteRejectsProtocolsInTOML(t *testing.T) {
	t.Parallel()
	tests := map[string]*cassetter.Cassette{
		"gRPC": {
			Version: 1,
			GRPCInteractions: []cassetter.GRPCInteraction{{
				Request: cassetter.GRPCRequest{Method: "/example.Service/Get"},
			}},
		},
		"WebSocket": {
			Version: 1,
			WebSocketInteractions: []cassetter.WebSocketInteraction{{
				URI: "wss://example.com/socket",
			}},
		},
	}
	for name, cassette := range tests {
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			err := cassette.Save(filepath.Join(t.TempDir(), "cassette.toml"))
			if err == nil || !strings.Contains(err.Error(), "TOML cassettes cannot store") {
				t.Fatalf("save error = %v", err)
			}
		})
	}
}

func TestCassetteRejectsUnknownSectionsInTOML(t *testing.T) {
	t.Parallel()
	directory := t.TempDir()
	yamlPath := filepath.Join(directory, "cassette.yaml")
	content := "version: 1\ninteractions: []\nfuture_interactions:\n  - value\n"
	if err := os.WriteFile(yamlPath, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	cassette, err := cassetter.Load(yamlPath)
	if err != nil {
		t.Fatal(err)
	}
	err = cassette.Save(filepath.Join(directory, "cassette.toml"))
	if err == nil || !strings.Contains(err.Error(), "unrecognized top-level sections") {
		t.Fatalf("save error = %v", err)
	}
}

func TestCassetteRejectsInvalidTOMLBodies(t *testing.T) {
	t.Parallel()
	bodies := map[string]string{
		"JSON":   `body_type = "json"\nbody_content = "{"`,
		"binary": `body_type = "binary"\nbody_content = "xyz"`,
		"type":   `body_type = "xml"\nbody_content = "value"`,
	}
	for name, body := range bodies {
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			content := `version = 1
[[interactions]]
[interactions.request]
method = "GET"
uri = "https://example.com"
` + strings.ReplaceAll(body, `\n`, "\n") + `
[interactions.response]
status = 200
body_type = "none"
`
			path := filepath.Join(t.TempDir(), "invalid.toml")
			if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
				t.Fatal(err)
			}
			if _, err := cassetter.Load(path); err == nil {
				t.Fatal("Load accepted invalid TOML body")
			}
		})
	}
}

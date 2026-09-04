package cassetter_test

import (
	"bytes"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Kludex/cassetter/go"
)

func TestLoadAndSaveExistingFormat(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	content := `version: 1
interactions:
  - request:
      method: POST
      uri: https://example.com/items
      headers:
        content-type:
          - application/json
      body:
        type: json
        content:
          name: example
    response:
      status: 200
      headers: {}
      body:
        type: binary
        content: 00ff
    recorded_at: '2026-01-01T00:00:00Z'
grpc_interactions:
  - request:
      method: /example.Service/Get
      body:
        type: binary
        content: ""
    response:
      status_code: 0
      body:
        type: binary
        content: ""
future_interactions:
  - value: retained
`
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	cassette, err := cassetter.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if got := cassette.Interactions[0].Response.Body.Content; !bytes.Equal(got.([]byte), []byte{0, 255}) {
		t.Fatalf("binary body = %v", got)
	}
	if got := cassette.GRPCInteractions[0].Request.Method; got != "/example.Service/Get" {
		t.Fatalf("gRPC method = %q", got)
	}
	if got := cassette.GRPCInteractions[0].Response.StatusMessage; got != "OK" {
		t.Fatalf("gRPC status message = %q", got)
	}
	if err := cassette.Save(path); err != nil {
		t.Fatal(err)
	}
	saved, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(saved), "grpc_interactions:") {
		t.Fatal("Save removed the gRPC section")
	}
	if !strings.Contains(string(saved), "future_interactions:") {
		t.Fatal("Save removed an unknown protocol section")
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("permissions = %o", info.Mode().Perm())
	}
}

func TestSaveRejectsInvalidInteractions(t *testing.T) {
	t.Parallel()
	tests := map[string]*cassetter.Cassette{
		"method": {
			Version: 1,
			Interactions: []cassetter.HTTPInteraction{{
				Request:  cassetter.HTTPRequest{URI: "https://example.com"},
				Response: cassetter.HTTPResponse{Status: 200},
			}},
		},
		"URI": {
			Version: 1,
			Interactions: []cassetter.HTTPInteraction{{
				Request:  cassetter.HTTPRequest{Method: "GET"},
				Response: cassetter.HTTPResponse{Status: 200},
			}},
		},
		"status": {
			Version: 1,
			Interactions: []cassetter.HTTPInteraction{{
				Request:  cassetter.HTTPRequest{Method: "GET", URI: "https://example.com"},
				Response: cassetter.HTTPResponse{Status: 0},
			}},
		},
		"WebSocket direction": {
			Version: 1,
			WebSocketInteractions: []cassetter.WebSocketInteraction{{
				URI:    "wss://example.com",
				Frames: []cassetter.WebSocketFrame{{FrameType: "text"}},
			}},
		},
		"WebSocket frame type": {
			Version: 1,
			WebSocketInteractions: []cassetter.WebSocketInteraction{{
				URI:    "wss://example.com",
				Frames: []cassetter.WebSocketFrame{{Direction: "send"}},
			}},
		},
	}
	for name, cassette := range tests {
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			if err := cassette.Save(filepath.Join(t.TempDir(), "invalid.yaml")); err == nil {
				t.Fatal("Save accepted an invalid interaction")
			}
		})
	}
}

func TestSaveRejectsInvalidBody(t *testing.T) {
	t.Parallel()
	bodies := []cassetter.Body{
		{Type: cassetter.BodyTypeText, Content: []byte("not text")},
		{Type: cassetter.BodyTypeJSON, Content: map[any]any{1: "not JSON"}},
	}
	for index, body := range bodies {
		cassette := &cassetter.Cassette{
			Version: 1,
			Interactions: []cassetter.HTTPInteraction{{
				Request: cassetter.HTTPRequest{Method: "GET", URI: "https://example.com"},
				Response: cassetter.HTTPResponse{
					Status: 200,
					Body:   body,
				},
			}},
		}
		path := filepath.Join(t.TempDir(), fmt.Sprintf("invalid-%d.yaml", index))
		if err := cassette.Save(path); err == nil {
			t.Fatal("Save accepted an invalid body")
		}
	}
}

func TestSaveRejectsNonFiniteGRPCDebugData(t *testing.T) {
	t.Parallel()
	cassette := &cassetter.Cassette{
		Version: 1,
		GRPCInteractions: []cassetter.GRPCInteraction{{
			Request:   cassetter.GRPCRequest{Method: "/example.Service/Get"},
			JSONDebug: map[string]any{"value": math.NaN()},
		}},
	}
	if err := cassette.Save(filepath.Join(t.TempDir(), "invalid.yaml")); err == nil {
		t.Fatal("Save accepted non-finite gRPC debug data")
	}
}

func TestLoadRejectsInvalidJSONBody(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "invalid.yaml")
	content := `version: 1
interactions:
  - request:
      method: GET
      uri: https://example.com
      body:
        type: none
    response:
      status: 200
      body:
        type: json
        content:
          1: not JSON
`
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := cassetter.Load(path); err == nil {
		t.Fatal("Load accepted invalid JSON content")
	}
}

func TestLoadRejectsUnknownVersion(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	if err := os.WriteFile(path, []byte("version: 2\ninteractions: []\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := cassetter.Load(path); err == nil {
		t.Fatal("Load accepted an unknown format version")
	}
}

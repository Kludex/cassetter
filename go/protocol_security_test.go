package cassetter_test

import (
	"encoding/json"
	"net/http"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Kludex/cassetter/go"
)

func TestScrubFiltersGRPCAndWebSocketSecrets(t *testing.T) {
	t.Parallel()
	cassette := &cassetter.Cassette{
		Version: 1,
		GRPCInteractions: []cassetter.GRPCInteraction{{
			Request: cassetter.GRPCRequest{
				Method:   "/example.Service/Get",
				Metadata: http.Header{"Authorization": {"Bearer secret"}},
				Body: cassetter.Body{
					Type:    cassetter.BodyTypeJSON,
					Content: map[string]any{"password": "secret"},
				},
			},
			Response: cassetter.GRPCResponse{
				Metadata: http.Header{"Set-Cookie": {"session=secret"}},
			},
			JSONDebug: map[string]any{
				"access_token": "secret",
				"sequence":     int64(9_007_199_254_740_993),
			},
		}},
		WebSocketInteractions: []cassetter.WebSocketInteraction{{
			URI:     "wss://example.com/stream?token=secret",
			Headers: http.Header{"X-API-Key": {"secret"}},
			Frames: []cassetter.WebSocketFrame{{
				Direction: "send",
				FrameType: "text",
				Body: cassetter.Body{
					Type:    cassetter.BodyTypeJSON,
					Content: map[string]any{"client_secret": "secret"},
				},
			}},
		}},
	}

	cassette.Scrub(cassetter.DefaultSecurityConfig())

	grpc := cassette.GRPCInteractions[0]
	if grpc.Request.Metadata.Get("Authorization") != "" || grpc.Response.Metadata.Get("Set-Cookie") != "" {
		t.Fatal("gRPC metadata secrets were not removed")
	}
	if grpc.Request.Body.Content.(map[string]any)["password"] != "[FILTERED]" {
		t.Fatal("gRPC body secret was not filtered")
	}
	if grpc.JSONDebug.(map[string]any)["access_token"] != "[FILTERED]" {
		t.Fatal("gRPC debug secret was not filtered")
	}
	assertLargeJSONNumber(t, grpc.JSONDebug)
	webSocket := cassette.WebSocketInteractions[0]
	if webSocket.Headers.Get("X-API-Key") != "" {
		t.Fatal("WebSocket header secret was not removed")
	}
	if webSocket.URI != "wss://example.com/stream?token=[FILTERED]" {
		t.Fatalf("WebSocket URI = %q", webSocket.URI)
	}
	if webSocket.Frames[0].Body.Content.(map[string]any)["client_secret"] != "[FILTERED]" {
		t.Fatal("WebSocket frame secret was not filtered")
	}

	path := filepath.Join(t.TempDir(), "cassette.yaml")
	if err := cassette.Save(path); err != nil {
		t.Fatal(err)
	}
	reloaded, err := cassetter.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	assertLargeJSONNumber(t, reloaded.GRPCInteractions[0].JSONDebug)
}

func assertLargeJSONNumber(t *testing.T, value any) {
	t.Helper()
	encoded, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(encoded), `"sequence":9007199254740993`) {
		t.Fatalf("JSON debug data = %s", encoded)
	}
}

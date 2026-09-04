package cassetter_test

import (
	"net/http"
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
			JSONDebug: map[string]any{"access_token": "secret"},
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
}

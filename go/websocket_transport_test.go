package cassetter_test

import (
	"context"
	"net/http"
	"path/filepath"
	"testing"

	"github.com/Kludex/cassetter/go"
	"github.com/coder/websocket"
)

func TestWebSocketTransportRecordsAndReplaysMessages(t *testing.T) {
	t.Parallel()
	server, serverResult := startWebSocketTestServer(t)
	path := filepath.Join(t.TempDir(), "websocket.yaml")
	uri := webSocketURL(server) + "/stream?token=secret"
	recorder := cassetter.NewWebSocketRecorder(
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeAll),
	)
	options := &websocket.DialOptions{
		HTTPClient:   server.Client(),
		HTTPHeader:   http.Header{"Authorization": {"secret"}, "X-Request": {"request"}},
		Subprotocols: []string{"chat"},
	}
	connection, response, err := recorder.DialWebSocket(context.Background(), uri, options)
	if err != nil {
		t.Fatalf("dial WebSocket: %v", err)
	}
	if response == nil || response.StatusCode != http.StatusSwitchingProtocols {
		t.Fatalf("handshake response = %v, want switching protocols", response)
	}
	connection.SetReadLimit(1024)
	if got := connection.Subprotocol(); got != "chat" {
		t.Fatalf("subprotocol = %q, want chat", got)
	}
	exerciseLiveWebSocket(t, connection)
	if err := connection.Close(websocket.StatusNormalClosure, "done"); err != nil {
		t.Fatalf("close WebSocket: %v", err)
	}
	if err := <-serverResult; err != nil {
		t.Fatalf("WebSocket server: %v", err)
	}
	if err := recorder.Close(); err != nil {
		t.Fatalf("close recorder: %v", err)
	}

	cassette, err := cassetter.Load(path)
	if err != nil {
		t.Fatalf("load cassette: %v", err)
	}
	if len(cassette.WebSocketInteractions) != 1 {
		t.Fatalf("got %d WebSocket interactions, want 1", len(cassette.WebSocketInteractions))
	}
	interaction := cassette.WebSocketInteractions[0]
	if interaction.URI != webSocketURL(server)+"/stream?token=[FILTERED]" {
		t.Fatalf("recorded URI = %q", interaction.URI)
	}
	if got := grpcHeaderValues(interaction.Headers, "authorization"); len(got) != 0 {
		t.Fatalf("recorded authorization header = %v", got)
	}
	if got := grpcHeaderValues(interaction.Headers, "x-request"); len(got) != 1 || got[0] != "request" {
		t.Fatalf("recorded x-request header = %v", got)
	}
	if got := grpcHeaderValues(interaction.Headers, "sec-websocket-protocol"); len(got) != 1 || got[0] != "chat" {
		t.Fatalf("recorded subprotocol = %v, want chat", got)
	}
	assertRecordedWebSocketFrames(t, interaction.Frames)

	server.Close()
	replayer := cassetter.NewTestWebSocketRecorder(
		t,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
	)
	replay, replayResponse, err := replayer.DialWebSocket(context.Background(), uri, nil)
	if err != nil {
		t.Fatalf("dial replay WebSocket: %v", err)
	}
	if replayResponse == nil || replayResponse.StatusCode != http.StatusSwitchingProtocols {
		t.Fatalf("replay handshake response = %v, want switching protocols", replayResponse)
	}
	if got := replay.Subprotocol(); got != "chat" {
		t.Fatalf("replay subprotocol = %q, want chat", got)
	}
	if err := replay.Ping(context.Background()); err != nil {
		t.Fatalf("ping replay WebSocket: %v", err)
	}
	exerciseReplayWebSocket(t, replay)
	_, _, err = replay.Read(context.Background())
	if websocket.CloseStatus(err) != websocket.StatusNormalClosure {
		t.Fatalf("exhausted replay error = %v, want normal closure", err)
	}
	if err := replay.Close(websocket.StatusNormalClosure, "done"); err != nil {
		t.Fatalf("close replay WebSocket: %v", err)
	}
	repeated, _, err := replayer.DialWebSocket(context.Background(), uri, nil)
	if err != nil {
		t.Fatalf("dial repeated replay WebSocket: %v", err)
	}
	if _, content, err := repeated.Read(context.Background()); err != nil || string(content) != "café" {
		t.Fatalf("repeated replay message = %q, %v", content, err)
	}
	if err := repeated.CloseNow(); err != nil {
		t.Fatalf("close repeated replay WebSocket: %v", err)
	}
}

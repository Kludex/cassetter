package cassetter_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"github.com/Kludex/cassetter/go"
	"github.com/coder/websocket"
)

func TestWebSocketRecorderFinalizesRemoteClose(t *testing.T) {
	t.Parallel()
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		connection, err := websocket.Accept(writer, request, nil)
		if err != nil {
			return
		}
		if err := connection.Write(request.Context(), websocket.MessageText, []byte("message")); err != nil {
			return
		}
		_ = connection.Close(websocket.StatusPolicyViolation, "denied")
	}))
	t.Cleanup(server.Close)
	path := filepath.Join(t.TempDir(), "remote-close.yaml")
	recorder := cassetter.NewWebSocketRecorder(
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeAll),
	)
	connection, _, err := recorder.DialWebSocket(
		context.Background(),
		webSocketURL(server),
		&websocket.DialOptions{HTTPClient: server.Client()},
	)
	if err != nil {
		t.Fatalf("dial WebSocket: %v", err)
	}
	if _, content, err := connection.Read(context.Background()); err != nil || string(content) != "message" {
		t.Fatalf("read WebSocket message = %q, %v", content, err)
	}
	if _, _, err := connection.Read(context.Background()); websocket.CloseStatus(err) != websocket.StatusPolicyViolation {
		t.Fatalf("remote close error = %v, want policy violation", err)
	}
	if err := recorder.Close(); err != nil {
		t.Fatalf("close recorder: %v", err)
	}
	cassette, err := cassetter.Load(path)
	if err != nil {
		t.Fatalf("load cassette: %v", err)
	}
	if got := len(cassette.WebSocketInteractions[0].Frames); got != 2 {
		t.Fatalf("recorded frames = %d, want 2", got)
	}

	server.Close()
	replayer := cassetter.NewTestWebSocketRecorder(
		t,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
	)
	replay, _, err := replayer.DialWebSocket(context.Background(), webSocketURL(server), nil)
	if err != nil {
		t.Fatalf("dial replay WebSocket: %v", err)
	}
	if _, content, err := replay.Read(context.Background()); err != nil || string(content) != "message" {
		t.Fatalf("read replay message = %q, %v", content, err)
	}
	_, _, err = replay.Read(context.Background())
	var closeError websocket.CloseError
	if !errors.As(err, &closeError) || closeError.Code != websocket.StatusPolicyViolation || closeError.Reason != "denied" {
		t.Fatalf("replayed close error = %v, want policy violation denied", err)
	}
}

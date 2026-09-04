package cassetter_test

import (
	"context"
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
		_ = connection.Close(websocket.StatusNormalClosure, "done")
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
	if _, _, err := connection.Read(context.Background()); websocket.CloseStatus(err) != websocket.StatusNormalClosure {
		t.Fatalf("remote close error = %v, want normal closure", err)
	}
	if err := recorder.Close(); err != nil {
		t.Fatalf("close recorder: %v", err)
	}
	cassette, err := cassetter.Load(path)
	if err != nil {
		t.Fatalf("load cassette: %v", err)
	}
	if got := len(cassette.WebSocketInteractions[0].Frames); got != 1 {
		t.Fatalf("recorded frames = %d, want 1", got)
	}
}

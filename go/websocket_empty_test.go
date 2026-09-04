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

func TestWebSocketRecorderPersistsEmptyConnection(t *testing.T) {
	t.Parallel()
	serverResult := make(chan error, 1)
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		connection, err := websocket.Accept(writer, request, &websocket.AcceptOptions{Subprotocols: []string{"chat"}})
		if err != nil {
			serverResult <- err
			return
		}
		defer func() {
			_ = connection.CloseNow()
		}()
		_, _, err = connection.Read(request.Context())
		if websocket.CloseStatus(err) == websocket.StatusNormalClosure {
			err = nil
		}
		serverResult <- err
	}))
	t.Cleanup(server.Close)
	path := filepath.Join(t.TempDir(), "empty.yaml")
	recorder := cassetter.NewWebSocketRecorder(
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeAll),
	)
	connection, _, err := recorder.DialWebSocket(
		context.Background(),
		webSocketURL(server),
		&websocket.DialOptions{HTTPClient: server.Client(), Subprotocols: []string{"chat"}},
	)
	if err != nil {
		t.Fatalf("dial WebSocket: %v", err)
	}
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
	interaction := cassette.WebSocketInteractions[0]
	if len(interaction.Frames) != 0 {
		t.Fatalf("recorded frames = %v, want empty", interaction.Frames)
	}
	if got := grpcHeaderValues(interaction.Headers, "sec-websocket-protocol"); len(got) != 1 || got[0] != "chat" {
		t.Fatalf("recorded subprotocol = %v, want chat", got)
	}
}

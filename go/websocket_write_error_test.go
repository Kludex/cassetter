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

func TestWebSocketRecorderFinalizesTerminalWriteError(t *testing.T) {
	t.Parallel()
	serverClosed := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		connection, err := websocket.Accept(writer, request, nil)
		if err != nil {
			return
		}
		_ = connection.CloseNow()
		close(serverClosed)
	}))
	t.Cleanup(server.Close)
	path := filepath.Join(t.TempDir(), "write-error.yaml")
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
	<-serverClosed
	var writeErr error
	for range 10 {
		writeErr = connection.Write(context.Background(), websocket.MessageText, make([]byte, 64*1024))
		if writeErr != nil {
			break
		}
	}
	if writeErr == nil {
		t.Fatal("writes to closed WebSocket returned no error")
	}
	if err := recorder.Close(); err != nil {
		t.Fatalf("close recorder: %v", err)
	}
	cassette, err := cassetter.Load(path)
	if err != nil {
		t.Fatalf("load cassette: %v", err)
	}
	frames := cassette.WebSocketInteractions[0].Frames
	if len(frames) == 0 || frames[len(frames)-1].FrameType != "close" {
		t.Fatalf("recorded frames = %v, want terminal close", frames)
	}
}

package cassetter_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"github.com/Kludex/cassetter/go"
	"github.com/coder/websocket"
)

func TestWebSocketTransportBypassesLocalhost(t *testing.T) {
	t.Parallel()
	serverResult := make(chan error, 1)
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		connection, err := websocket.Accept(writer, request, nil)
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
	path := filepath.Join(t.TempDir(), "bypassed.yaml")
	recorder := cassetter.NewWebSocketRecorder(
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeAll),
		cassetter.WithIgnoreLocalhost(),
	)
	connection, _, err := recorder.DialWebSocket(
		context.Background(),
		webSocketURL(server),
		&websocket.DialOptions{HTTPClient: server.Client()},
	)
	if err != nil {
		t.Fatalf("dial WebSocket: %v", err)
	}
	if err := recorder.Close(); err != nil {
		t.Fatalf("close recorder with bypassed connection: %v", err)
	}
	if err := connection.Close(websocket.StatusNormalClosure, "done"); err != nil {
		t.Fatalf("close bypassed WebSocket: %v", err)
	}
	if err := <-serverResult; err != nil {
		t.Fatalf("WebSocket server: %v", err)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("bypassed cassette stat error = %v, want not exist", err)
	}
}

package cassetter_test

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/coder/websocket"
)

func startWebSocketTestServer(t *testing.T) (*httptest.Server, <-chan error) {
	t.Helper()
	result := make(chan error, 1)
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		connection, err := websocket.Accept(writer, request, &websocket.AcceptOptions{Subprotocols: []string{"chat"}})
		if err != nil {
			result <- err
			return
		}
		defer func() {
			_ = connection.CloseNow()
		}()
		for range 3 {
			messageType, content, err := connection.Read(request.Context())
			if err != nil {
				result <- err
				return
			}
			if err := connection.Write(request.Context(), messageType, content); err != nil {
				result <- err
				return
			}
		}
		_, _, err = connection.Read(request.Context())
		if websocket.CloseStatus(err) != websocket.StatusNormalClosure {
			result <- errors.New("WebSocket client did not close normally")
			return
		}
		result <- nil
	}))
	t.Cleanup(server.Close)
	return server, result
}

func webSocketURL(server *httptest.Server) string {
	return "ws" + server.URL[len("http"):]
}

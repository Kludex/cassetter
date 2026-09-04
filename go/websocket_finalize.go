package cassetter

import (
	"bytes"
	"context"
	"errors"
	"sync"
	"time"

	"github.com/coder/websocket"
)

func (c *WebSocketConn) finalize() error {
	c.finish.Do(func() {
		if c.transport == nil {
			return
		}
		c.readMu.Lock()
		c.writeMu.Lock()
		c.mu.Lock()
		frames := append([]WebSocketFrame(nil), c.frames...)
		c.frames = nil
		c.mu.Unlock()
		c.writeMu.Unlock()
		c.readMu.Unlock()
		if len(frames) == 0 {
			c.transport.finishWebSocketRecording(c.order, nil)
			return
		}
		c.finishErr = c.transport.recordWebSocket(WebSocketInteraction{
			URI:        c.uri,
			Headers:    c.headers,
			Frames:     frames,
			RecordedAt: time.Now().UTC().Format(time.RFC3339Nano),
		}, c.order)
	})
	return c.finishErr
}

func joinWebSocketErrors(callErr error, recordingErr error) error {
	if callErr == nil {
		return recordingErr
	}
	if recordingErr == nil {
		return callErr
	}
	return errors.Join(callErr, recordingErr)
}

type webSocketMessageWriter struct {
	ctx         context.Context
	connection  *WebSocketConn
	messageType websocket.MessageType
	mu          sync.Mutex
	content     bytes.Buffer
	closed      bool
}

func (w *webSocketMessageWriter) Write(content []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.closed {
		return 0, errors.New("cassetter: WebSocket message writer is closed")
	}
	return w.content.Write(content)
}

func (w *webSocketMessageWriter) Close() error {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.closed {
		return nil
	}
	w.closed = true
	return w.connection.Write(w.ctx, w.messageType, w.content.Bytes())
}

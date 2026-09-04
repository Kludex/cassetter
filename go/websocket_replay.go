package cassetter

import (
	"context"
	"errors"
	"sync"

	"github.com/coder/websocket"
)

type replayWebSocketConn struct {
	frames []WebSocketFrame
	mu     sync.Mutex
	next   int
	closed bool
}

func newReplayWebSocketConn(interaction WebSocketInteraction) *WebSocketConn {
	frames := make([]WebSocketFrame, 0, len(interaction.Frames))
	for _, frame := range interaction.Frames {
		if frame.Direction == "recv" {
			frames = append(frames, frame)
		}
	}
	return &WebSocketConn{replay: &replayWebSocketConn{frames: frames}}
}

func (c *replayWebSocketConn) read(ctx context.Context) (websocket.MessageType, []byte, error) {
	if err := ctx.Err(); err != nil {
		return 0, nil, err
	}
	c.mu.Lock()
	if c.closed || c.next >= len(c.frames) {
		c.closed = true
		c.mu.Unlock()
		return 0, nil, websocket.CloseError{Code: websocket.StatusNormalClosure, Reason: "cassette replay exhausted"}
	}
	frame := c.frames[c.next]
	c.next++
	c.mu.Unlock()
	content, err := bodyBytes(frame.Body)
	if err != nil {
		return 0, nil, err
	}
	switch frame.FrameType {
	case "text":
		return websocket.MessageText, content, nil
	case "binary":
		return websocket.MessageBinary, content, nil
	default:
		return 0, nil, errors.New("recorded WebSocket frame type must be text or binary")
	}
}

func (c *replayWebSocketConn) write(ctx context.Context, messageType websocket.MessageType) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if messageType != websocket.MessageText && messageType != websocket.MessageBinary {
		return errors.New("cassetter: WebSocket message type must be text or binary")
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return websocket.CloseError{Code: websocket.StatusNormalClosure, Reason: "cassette replay closed"}
	}
	return nil
}

func (c *replayWebSocketConn) ping(ctx context.Context) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return websocket.CloseError{Code: websocket.StatusNormalClosure, Reason: "cassette replay closed"}
	}
	return nil
}

func (c *replayWebSocketConn) close() error {
	c.mu.Lock()
	c.closed = true
	c.mu.Unlock()
	return nil
}

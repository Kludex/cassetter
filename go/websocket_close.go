package cassetter

import (
	"encoding/binary"
	"errors"
	"fmt"
	"time"

	"github.com/coder/websocket"
)

func (c *WebSocketConn) appendCloseFrame(err error) {
	var closeError websocket.CloseError
	if !errors.As(err, &closeError) {
		return
	}
	content := make([]byte, 2+len(closeError.Reason))
	binary.BigEndian.PutUint16(content, uint16(closeError.Code))
	copy(content[2:], closeError.Reason)
	offset := time.Since(c.startedAt).Milliseconds()
	if offset < 0 {
		offset = 0
	}
	c.mu.Lock()
	c.frames = append(c.frames, WebSocketFrame{
		Direction: "recv",
		FrameType: "close",
		Body:      Body{Type: BodyTypeBinary, Content: content},
		OffsetMS:  uint64(offset),
	})
	c.mu.Unlock()
}

func replayWebSocketClose(frame WebSocketFrame) (websocket.CloseError, error) {
	if frame.Body.Type != BodyTypeBinary {
		return websocket.CloseError{}, fmt.Errorf("recorded WebSocket close body has type %q, want binary", frame.Body.Type)
	}
	content, err := bodyBytes(frame.Body)
	if err != nil {
		return websocket.CloseError{}, fmt.Errorf("decode recorded WebSocket close: %w", err)
	}
	if len(content) < 2 {
		return websocket.CloseError{}, errors.New("recorded WebSocket close body is shorter than its status code")
	}
	return websocket.CloseError{
		Code:   websocket.StatusCode(binary.BigEndian.Uint16(content)),
		Reason: string(content[2:]),
	}, nil
}

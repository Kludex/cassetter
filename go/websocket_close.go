package cassetter

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"time"

	"github.com/coder/websocket"
)

func (c *WebSocketConn) appendCloseFrame(err error) {
	var closeError websocket.CloseError
	if !errors.As(err, &closeError) {
		if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
			return
		}
		closeError.Code = websocket.StatusAbnormalClosure
	}
	content := make([]byte, 2+len(closeError.Reason))
	binary.BigEndian.PutUint16(content, uint16(closeError.Code))
	copy(content[2:], closeError.Reason)
	offset := time.Since(c.startedAt).Milliseconds()
	if offset < 0 {
		offset = 0
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.terminal {
		return
	}
	c.terminal = true
	c.frames = append(c.frames, WebSocketFrame{
		Direction: "recv",
		FrameType: "close",
		Body:      Body{Type: BodyTypeBinary, Content: content},
		OffsetMS:  uint64(offset),
	})
}

func scrubWebSocketCloseBody(body Body, patterns []string, replacement string) Body {
	if body.Type != BodyTypeBinary {
		return body
	}
	content, ok := body.Content.([]byte)
	if !ok || len(content) < 2 {
		return body
	}
	reason := scrubBody(Body{Type: BodyTypeText, Content: string(content[2:])}, patterns, replacement)
	scrubbedReason, err := bodyBytes(reason)
	if err != nil {
		return body
	}
	scrubbed := append([]byte(nil), content[:2]...)
	scrubbed = append(scrubbed, scrubbedReason...)
	return Body{Type: BodyTypeBinary, Content: scrubbed}
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

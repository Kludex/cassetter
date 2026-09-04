package cassetter

import (
	"bytes"
	"context"
	"errors"
	"io"
	"sync"
	"time"

	"github.com/coder/websocket"
	"golang.org/x/text/unicode/norm"
)

// WebSocketConn records or replays messages through the coder/websocket API.
type WebSocketConn struct {
	live      *websocket.Conn
	replay    *replayWebSocketConn
	transport *Transport
	uri       string
	headers   map[string][]string
	startedAt time.Time
	order     uint64

	readMu    sync.Mutex
	writeMu   sync.Mutex
	mu        sync.Mutex
	frames    []WebSocketFrame
	finish    sync.Once
	finishErr error
}

// Read reads one complete WebSocket message.
func (c *WebSocketConn) Read(ctx context.Context) (websocket.MessageType, []byte, error) {
	if c.replay != nil {
		return c.replay.read(ctx)
	}
	if c.transport == nil {
		return c.live.Read(ctx)
	}
	c.readMu.Lock()
	messageType, content, err := c.live.Read(ctx)
	if err == nil {
		err = c.appendFrame("recv", messageType, content)
	} else {
		c.appendCloseFrame(err)
	}
	c.readMu.Unlock()
	if err != nil {
		return messageType, content, joinWebSocketErrors(err, c.finalize())
	}
	return messageType, content, nil
}

// Reader returns a reader for one complete WebSocket message.
func (c *WebSocketConn) Reader(ctx context.Context) (websocket.MessageType, io.Reader, error) {
	messageType, content, err := c.Read(ctx)
	if err != nil {
		return messageType, nil, err
	}
	return messageType, bytes.NewReader(content), nil
}

// Write writes one complete WebSocket message.
func (c *WebSocketConn) Write(ctx context.Context, messageType websocket.MessageType, content []byte) error {
	if c.replay != nil {
		return c.replay.write(ctx, messageType)
	}
	if c.transport == nil {
		return c.live.Write(ctx, messageType, content)
	}
	c.writeMu.Lock()
	err := c.live.Write(ctx, messageType, content)
	if err == nil {
		err = c.appendFrame("send", messageType, content)
	}
	c.writeMu.Unlock()
	return err
}

// Writer returns a writer that sends one WebSocket message when closed.
func (c *WebSocketConn) Writer(ctx context.Context, messageType websocket.MessageType) (io.WriteCloser, error) {
	if messageType != websocket.MessageText && messageType != websocket.MessageBinary {
		return nil, errors.New("cassetter: WebSocket message type must be text or binary")
	}
	return &webSocketMessageWriter{ctx: ctx, connection: c, messageType: messageType}, nil
}

// Ping sends a ping to a live connection and is a no-op during replay.
func (c *WebSocketConn) Ping(ctx context.Context) error {
	if c.replay != nil {
		return c.replay.ping(ctx)
	}
	return c.live.Ping(ctx)
}

// SetReadLimit sets the maximum size of a message read from a live connection.
func (c *WebSocketConn) SetReadLimit(limit int64) {
	if c.live != nil {
		c.live.SetReadLimit(limit)
	}
}

// Subprotocol returns the negotiated subprotocol for a live connection.
func (c *WebSocketConn) Subprotocol() string {
	if c.live == nil {
		return ""
	}
	return c.live.Subprotocol()
}

// Close performs a WebSocket close handshake and saves recorded frames.
func (c *WebSocketConn) Close(code websocket.StatusCode, reason string) error {
	if c.replay != nil {
		return c.replay.close()
	}
	return joinWebSocketErrors(c.live.Close(code, reason), c.finalize())
}

// CloseNow closes immediately and saves recorded frames.
func (c *WebSocketConn) CloseNow() error {
	if c.replay != nil {
		return c.replay.close()
	}
	return joinWebSocketErrors(c.live.CloseNow(), c.finalize())
}

func (c *WebSocketConn) appendFrame(direction string, messageType websocket.MessageType, content []byte) error {
	frameType, body, err := webSocketFrameBody(messageType, content)
	if err != nil {
		return err
	}
	offset := time.Since(c.startedAt).Milliseconds()
	if offset < 0 {
		offset = 0
	}
	c.mu.Lock()
	c.frames = append(c.frames, WebSocketFrame{
		Direction: direction,
		FrameType: frameType,
		Body:      body,
		OffsetMS:  uint64(offset),
	})
	c.mu.Unlock()
	return nil
}

func webSocketFrameBody(messageType websocket.MessageType, content []byte) (string, Body, error) {
	switch messageType {
	case websocket.MessageText:
		value := norm.NFC.String(string(bytes.ToValidUTF8(content, []byte("�"))))
		return "text", Body{Type: BodyTypeText, Content: value}, nil
	case websocket.MessageBinary:
		return "binary", Body{Type: BodyTypeBinary, Content: bytes.Clone(content)}, nil
	default:
		return "", Body{}, errors.New("cassetter: WebSocket message type must be text or binary")
	}
}

package cassetter_test

import (
	"bytes"
	"context"
	"io"
	"testing"

	"github.com/Kludex/cassetter/go"
	"github.com/coder/websocket"
	"golang.org/x/text/unicode/norm"
)

func exerciseLiveWebSocket(t *testing.T, connection *cassetter.WebSocketConn) {
	t.Helper()
	writer, err := connection.Writer(context.Background(), websocket.MessageText)
	if err != nil {
		t.Fatalf("create WebSocket writer: %v", err)
	}
	if _, err := writer.Write([]byte("cafe\u0301")); err != nil {
		t.Fatalf("write WebSocket writer: %v", err)
	}
	if err := writer.Close(); err != nil {
		t.Fatalf("close WebSocket writer: %v", err)
	}
	if _, content, err := connection.Read(context.Background()); err != nil || string(content) != "cafe\u0301" {
		t.Fatalf("read text echo = %q, %v", content, err)
	}
	secret := []byte(`{"access_token":"secret","message":"hello"}`)
	if err := connection.Write(context.Background(), websocket.MessageText, secret); err != nil {
		t.Fatalf("write JSON WebSocket message: %v", err)
	}
	messageType, reader, err := connection.Reader(context.Background())
	if err != nil {
		t.Fatalf("create WebSocket reader: %v", err)
	}
	content, err := io.ReadAll(reader)
	if err != nil || messageType != websocket.MessageText || !bytes.Equal(content, secret) {
		t.Fatalf("read JSON echo = %q, %v", content, err)
	}
	binary := []byte{0xff, 0x00, 0x01}
	if err := connection.Write(context.Background(), websocket.MessageBinary, binary); err != nil {
		t.Fatalf("write binary WebSocket message: %v", err)
	}
	messageType, content, err = connection.Read(context.Background())
	if err != nil || messageType != websocket.MessageBinary || !bytes.Equal(content, binary) {
		t.Fatalf("read binary echo = %x, %v", content, err)
	}
}

func exerciseReplayWebSocket(t *testing.T, connection *cassetter.WebSocketConn) {
	t.Helper()
	for _, outgoing := range []struct {
		messageType websocket.MessageType
		content     []byte
	}{
		{messageType: websocket.MessageText, content: []byte("ignored")},
		{messageType: websocket.MessageText, content: []byte("ignored")},
		{messageType: websocket.MessageBinary, content: []byte("ignored")},
	} {
		if err := connection.Write(context.Background(), outgoing.messageType, outgoing.content); err != nil {
			t.Fatalf("write replay WebSocket: %v", err)
		}
	}
	messageType, content, err := connection.Read(context.Background())
	if err != nil || messageType != websocket.MessageText || string(content) != "café" {
		t.Fatalf("first replay message = %q, %v", content, err)
	}
	messageType, content, err = connection.Read(context.Background())
	expected := `{"access_token":"[FILTERED]","message":"hello"}`
	if err != nil || messageType != websocket.MessageText || string(content) != expected {
		t.Fatalf("second replay message = %q, %v", content, err)
	}
	messageType, content, err = connection.Read(context.Background())
	if err != nil || messageType != websocket.MessageBinary || !bytes.Equal(content, []byte{0xff, 0x00, 0x01}) {
		t.Fatalf("third replay message = %x, %v", content, err)
	}
}

func assertRecordedWebSocketFrames(t *testing.T, frames []cassetter.WebSocketFrame) {
	t.Helper()
	if len(frames) != 6 {
		t.Fatalf("got %d WebSocket frames, want 6", len(frames))
	}
	for index, frame := range frames {
		expectedDirection := "send"
		if index%2 == 1 {
			expectedDirection = "recv"
		}
		if frame.Direction != expectedDirection {
			t.Fatalf("frame %d direction = %q, want %q", index, frame.Direction, expectedDirection)
		}
	}
	if got := frames[0].Body.Content; got != norm.NFC.String("cafe\u0301") {
		t.Fatalf("recorded normalized text = %q", got)
	}
	if got := frames[2].Body.Content; got != `{"access_token":"[FILTERED]","message":"hello"}` {
		t.Fatalf("recorded scrubbed text = %q", got)
	}
}

package cassetter_test

import (
	"context"
	"errors"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Kludex/cassetter/go"
	"github.com/coder/websocket"
)

func TestWebSocketTransportReportsNoMatchAndClosedRecorder(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "missing.yaml")
	recorder := cassetter.NewWebSocketRecorder(
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
	)
	_, _, err := recorder.DialWebSocket(context.Background(), "ws://offline.example/socket", nil)
	if !errors.Is(err, cassetter.ErrNoMatch) {
		t.Fatalf("missing interaction error = %v, want ErrNoMatch", err)
	}
	var noMatch *cassetter.NoWebSocketMatchError
	if !errors.As(err, &noMatch) || noMatch.URI != "ws://offline.example/socket" {
		t.Fatalf("missing interaction error = %v, want typed URI", err)
	}
	if err := recorder.Close(); err != nil {
		t.Fatalf("close recorder: %v", err)
	}
	_, _, err = recorder.DialWebSocket(context.Background(), "ws://offline.example/socket", nil)
	if !errors.Is(err, cassetter.ErrTransportClosed) {
		t.Fatalf("closed recorder error = %v, want ErrTransportClosed", err)
	}
}

func TestWebSocketRecorderReportsIncompleteConnection(t *testing.T) {
	t.Parallel()
	server, _ := startWebSocketTestServer(t)
	recorder := cassetter.NewWebSocketRecorder(
		cassetter.WithPath(filepath.Join(t.TempDir(), "incomplete.yaml")),
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
	err = recorder.Close()
	if !errors.Is(err, cassetter.ErrIncompleteRecording) {
		t.Fatalf("close recorder error = %v, want ErrIncompleteRecording", err)
	}
	var incomplete *cassetter.IncompleteWebSocketRecordingError
	if !errors.As(err, &incomplete) || incomplete.URI != webSocketURL(server) {
		t.Fatalf("close recorder error = %v, want typed URI", err)
	}
	_ = connection.CloseNow()
}

func TestWebSocketReplayUsesURINormalizerAndValidatesFrames(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "normalized.yaml")
	cassette := &cassetter.Cassette{
		Version:      1,
		Interactions: []cassetter.HTTPInteraction{},
		WebSocketInteractions: []cassetter.WebSocketInteraction{{
			URI: "ws://offline.example/sessions/recorded",
			Frames: []cassetter.WebSocketFrame{{
				Direction: "recv",
				FrameType: "unsupported",
				Body:      cassetter.Body{Type: cassetter.BodyTypeNone},
			}},
		}},
	}
	if err := cassette.Save(path); err != nil {
		t.Fatalf("save cassette: %v", err)
	}
	recorder := cassetter.NewTestWebSocketRecorder(
		t,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
		cassetter.WithURINormalizer(func(uri string) string {
			prefix, _, _ := strings.Cut(uri, "/sessions/")
			return prefix + "/sessions/{id}"
		}),
	)
	connection, _, err := recorder.DialWebSocket(
		context.Background(),
		"ws://offline.example/sessions/current",
		nil,
	)
	if err != nil {
		t.Fatalf("dial normalized replay: %v", err)
	}
	if _, _, err := connection.Read(context.Background()); err == nil {
		t.Fatal("unsupported recorded frame returned no error")
	}
	if _, err := connection.Writer(context.Background(), websocket.MessageType(99)); err == nil {
		t.Fatal("unsupported writer message type returned no error")
	}
}

func TestWebSocketDialRejectsInvalidURI(t *testing.T) {
	t.Parallel()
	recorder := cassetter.NewTestWebSocketRecorder(
		t,
		cassetter.WithPath(filepath.Join(t.TempDir(), "invalid.yaml")),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
	)
	for _, uri := range []string{"https://example.com/socket", "ws:///socket", "ws://example.com/%"} {
		if _, _, err := recorder.DialWebSocket(context.Background(), uri, nil); err == nil {
			t.Fatalf("invalid WebSocket URI %q returned no error", uri)
		}
	}
}

func TestWebSocketDialHonorsCanceledContext(t *testing.T) {
	t.Parallel()
	recorder := cassetter.NewTestWebSocketRecorder(
		t,
		cassetter.WithPath(filepath.Join(t.TempDir(), "canceled.yaml")),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
	)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, _, err := recorder.DialWebSocket(ctx, "ws://offline.example/socket", nil)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("canceled dial error = %v, want context canceled", err)
	}
}

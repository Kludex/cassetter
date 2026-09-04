package cassetter

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"time"

	"github.com/coder/websocket"
)

// DialWebSocket opens or replays a WebSocket connection.
func (t *Transport) DialWebSocket(
	ctx context.Context,
	uri string,
	options *websocket.DialOptions,
) (*WebSocketConn, *http.Response, error) {
	if err := t.Initialize(); err != nil {
		return nil, nil, err
	}
	if err := t.checkOpen(); err != nil {
		return nil, nil, err
	}
	if err := ctx.Err(); err != nil {
		return nil, nil, err
	}
	parsed, err := url.Parse(uri)
	if err != nil {
		return nil, nil, fmt.Errorf("parse WebSocket URI: %w", err)
	}
	if parsed.Scheme != "ws" && parsed.Scheme != "wss" {
		return nil, nil, fmt.Errorf("cassetter: unsupported WebSocket URI scheme %q", parsed.Scheme)
	}
	if parsed.Host == "" {
		return nil, nil, errors.New("cassetter: WebSocket URI host is required")
	}
	if t.shouldBypass(parsed) {
		connection, response, err := websocket.Dial(ctx, uri, options)
		if err != nil {
			return nil, response, err
		}
		return &WebSocketConn{live: connection}, response, nil
	}
	if t.config.mode != RecordModeAll && t.config.mode != RecordModeRewrite {
		interaction, found, err := t.takeWebSocketMatch(uri)
		if err != nil {
			return nil, nil, err
		}
		if found {
			connection, err := newReplayWebSocketConn(interaction)
			if err != nil {
				return nil, nil, err
			}
			return connection, replayWebSocketResponse(parsed), nil
		}
	}
	if !t.canRecord {
		return nil, nil, &NoWebSocketMatchError{URI: uri}
	}
	order, err := t.reserveWebSocketRecording(uri)
	if err != nil {
		return nil, nil, err
	}
	connection, response, err := websocket.Dial(ctx, uri, options)
	if err != nil {
		t.finishWebSocketRecording(order, nil)
		return nil, response, err
	}
	var headers http.Header
	if options != nil {
		headers = recordHeaders(options.HTTPHeader)
	}
	if subprotocol := connection.Subprotocol(); subprotocol != "" {
		if headers == nil {
			headers = make(http.Header)
		}
		headers["sec-websocket-protocol"] = []string{subprotocol}
	}
	return &WebSocketConn{
		live:      connection,
		transport: t,
		uri:       uri,
		headers:   headers,
		startedAt: time.Now(),
		order:     order,
	}, response, nil
}

func replayWebSocketResponse(uri *url.URL) *http.Response {
	return &http.Response{
		Status:     "101 Switching Protocols",
		StatusCode: http.StatusSwitchingProtocols,
		Proto:      "HTTP/1.1",
		ProtoMajor: 1,
		ProtoMinor: 1,
		Header:     make(http.Header),
		Body:       http.NoBody,
		Request:    &http.Request{Method: http.MethodGet, URL: uri},
	}
}

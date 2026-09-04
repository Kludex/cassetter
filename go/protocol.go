package cassetter

import (
	"net/http"

	"gopkg.in/yaml.v3"
)

// GRPCRequest is a recorded gRPC request.
type GRPCRequest struct {
	Method   string      `yaml:"method"`
	Metadata http.Header `yaml:"metadata,omitempty"`
	Body     Body        `yaml:"body"`
}

// GRPCResponse is a recorded gRPC response.
type GRPCResponse struct {
	StatusCode    uint32      `yaml:"status_code"`
	StatusMessage string      `yaml:"status_message"`
	Metadata      http.Header `yaml:"metadata,omitempty"`
	Body          Body        `yaml:"body"`
}

// UnmarshalYAML reads a gRPC response and applies the shared status-message default.
func (r *GRPCResponse) UnmarshalYAML(node *yaml.Node) error {
	type response GRPCResponse
	value := response{StatusMessage: "OK"}
	if err := node.Decode(&value); err != nil {
		return err
	}
	*r = GRPCResponse(value)
	return nil
}

// GRPCInteraction pairs a gRPC request with its recorded response.
type GRPCInteraction struct {
	Request    GRPCRequest  `yaml:"request"`
	Response   GRPCResponse `yaml:"response"`
	JSONDebug  any          `yaml:"json_debug,omitempty"`
	RecordedAt string       `yaml:"recorded_at,omitempty"`
}

// WebSocketFrame is a recorded WebSocket frame.
type WebSocketFrame struct {
	Direction string `yaml:"direction"`
	FrameType string `yaml:"frame_type"`
	Body      Body   `yaml:"body"`
	OffsetMS  uint64 `yaml:"offset_ms"`
}

// WebSocketInteraction is a recorded WebSocket exchange.
type WebSocketInteraction struct {
	URI        string           `yaml:"uri"`
	Headers    http.Header      `yaml:"headers,omitempty"`
	Frames     []WebSocketFrame `yaml:"frames"`
	RecordedAt string           `yaml:"recorded_at,omitempty"`
}

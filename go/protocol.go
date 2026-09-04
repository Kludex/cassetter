package cassetter

import (
	"errors"
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

// UnmarshalYAML rejects incomplete gRPC responses before status code zero can be mistaken for success.
func (i *GRPCInteraction) UnmarshalYAML(node *yaml.Node) error {
	responseNode, found := mappingValue(node, "response")
	if !found {
		return errors.New("gRPC interaction response is required")
	}
	if _, found := mappingValue(responseNode, "status_code"); !found {
		return errors.New("gRPC response status_code is required")
	}
	type interaction GRPCInteraction
	var value interaction
	if err := node.Decode(&value); err != nil {
		return err
	}
	*i = GRPCInteraction(value)
	return nil
}

// WebSocketFrame is a recorded WebSocket frame.
type WebSocketFrame struct {
	Direction string `yaml:"direction"`
	FrameType string `yaml:"frame_type"`
	Body      Body   `yaml:"body"`
	OffsetMS  uint64 `yaml:"offset_ms"`
}

// UnmarshalYAML rejects frames without the descriptors required by the shared format.
func (f *WebSocketFrame) UnmarshalYAML(node *yaml.Node) error {
	if _, found := mappingValue(node, "direction"); !found {
		return errors.New("WebSocket frame direction is required")
	}
	if _, found := mappingValue(node, "frame_type"); !found {
		return errors.New("WebSocket frame frame_type is required")
	}
	type frame WebSocketFrame
	var value frame
	if err := node.Decode(&value); err != nil {
		return err
	}
	*f = WebSocketFrame(value)
	return nil
}

// WebSocketInteraction is a recorded WebSocket exchange.
type WebSocketInteraction struct {
	URI        string           `yaml:"uri"`
	Headers    http.Header      `yaml:"headers,omitempty"`
	Frames     []WebSocketFrame `yaml:"frames"`
	RecordedAt string           `yaml:"recorded_at,omitempty"`
}

func mappingValue(node *yaml.Node, key string) (*yaml.Node, bool) {
	if node.Kind != yaml.MappingNode {
		return nil, false
	}
	for index := 0; index+1 < len(node.Content); index += 2 {
		if node.Content[index].Value == key {
			return node.Content[index+1], true
		}
	}
	return nil, false
}

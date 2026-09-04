package cassetter

import (
	"encoding/hex"
	"fmt"
	"net/http"

	"gopkg.in/yaml.v3"
)

// BodyType identifies how a recorded body is represented.
type BodyType string

const (
	// BodyTypeNone represents an empty body.
	BodyTypeNone BodyType = "none"
	// BodyTypeJSON represents structured JSON.
	BodyTypeJSON BodyType = "json"
	// BodyTypeText represents UTF-8 text.
	BodyTypeText BodyType = "text"
	// BodyTypeBinary represents arbitrary bytes.
	BodyTypeBinary BodyType = "binary"
)

// Body is the typed body envelope used by the cassetter format.
type Body struct {
	Type    BodyType
	Content any
}

// MarshalYAML writes binary content as the hexadecimal string used by cassetter.
func (b Body) MarshalYAML() (any, error) {
	bodyType := b.Type
	if bodyType == "" {
		bodyType = BodyTypeNone
	}
	if bodyType == BodyTypeNone {
		return struct {
			Type BodyType `yaml:"type"`
		}{Type: bodyType}, nil
	}
	content := b.Content
	switch bodyType {
	case BodyTypeJSON:
	case BodyTypeText:
		if _, ok := content.(string); !ok {
			return nil, fmt.Errorf("text body content must be a string")
		}
	case BodyTypeBinary:
		bytes, ok := content.([]byte)
		if !ok {
			return nil, fmt.Errorf("binary body content must be []byte")
		}
		content = hex.EncodeToString(bytes)
	default:
		return nil, fmt.Errorf("unknown body type %q", bodyType)
	}
	return struct {
		Type    BodyType `yaml:"type"`
		Content any      `yaml:"content"`
	}{Type: bodyType, Content: content}, nil
}

// UnmarshalYAML reads a body envelope from the cassetter format.
func (b *Body) UnmarshalYAML(node *yaml.Node) error {
	var value struct {
		Type    BodyType `yaml:"type"`
		Content any      `yaml:"content"`
	}
	if err := node.Decode(&value); err != nil {
		return err
	}
	if value.Type == "" {
		value.Type = BodyTypeNone
	}
	if value.Type == BodyTypeBinary {
		text, ok := value.Content.(string)
		if !ok {
			return fmt.Errorf("binary body content must be a hexadecimal string")
		}
		content, err := hex.DecodeString(text)
		if err != nil {
			return fmt.Errorf("decode binary body: %w", err)
		}
		value.Content = content
	}
	if value.Type == BodyTypeText {
		if _, ok := value.Content.(string); !ok {
			return fmt.Errorf("text body content must be a string")
		}
	}
	if value.Type != BodyTypeNone && value.Type != BodyTypeJSON && value.Type != BodyTypeText &&
		value.Type != BodyTypeBinary {
		return fmt.Errorf("unknown body type %q", value.Type)
	}
	b.Type = value.Type
	b.Content = value.Content
	return nil
}

// HTTPRequest is a recorded HTTP request.
type HTTPRequest struct {
	Method  string      `yaml:"method"`
	URI     string      `yaml:"uri"`
	Headers http.Header `yaml:"headers,omitempty"`
	Body    Body        `yaml:"body"`
}

// HTTPResponse is a recorded HTTP response.
type HTTPResponse struct {
	Status  int         `yaml:"status"`
	Headers http.Header `yaml:"headers,omitempty"`
	Body    Body        `yaml:"body"`
}

// HTTPInteraction pairs a request with its recorded response.
type HTTPInteraction struct {
	Request    HTTPRequest  `yaml:"request"`
	Response   HTTPResponse `yaml:"response"`
	RecordedAt string       `yaml:"recorded_at,omitempty"`
}

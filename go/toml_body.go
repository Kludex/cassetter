package cassetter

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"

	"golang.org/x/text/unicode/norm"
)

func bodyToTOML(body Body) (BodyType, *string, error) {
	bodyType := body.Type
	if bodyType == "" {
		bodyType = BodyTypeNone
	}
	var content string
	switch bodyType {
	case BodyTypeNone:
		return bodyType, nil, nil
	case BodyTypeJSON:
		normalized, err := normalizeJSONValue(body.Content)
		if err != nil {
			return "", nil, fmt.Errorf("JSON body content: %w", err)
		}
		encoded, err := json.Marshal(normalized)
		if err != nil {
			return "", nil, fmt.Errorf("encode JSON body: %w", err)
		}
		content = string(encoded)
	case BodyTypeText:
		var ok bool
		content, ok = body.Content.(string)
		if !ok {
			return "", nil, fmt.Errorf("text body content must be a string")
		}
	case BodyTypeBinary:
		value, ok := body.Content.([]byte)
		if !ok {
			return "", nil, fmt.Errorf("binary body content must be []byte")
		}
		content = hex.EncodeToString(value)
	default:
		return "", nil, fmt.Errorf("unknown body type %q", bodyType)
	}
	return bodyType, &content, nil
}

func bodyFromTOML(bodyType BodyType, content *string) (Body, error) {
	if content == nil {
		return Body{Type: BodyTypeNone}, nil
	}
	switch bodyType {
	case BodyTypeJSON:
		decoder := json.NewDecoder(bytes.NewBufferString(*content))
		decoder.UseNumber()
		var value any
		if err := decoder.Decode(&value); err != nil {
			return Body{}, fmt.Errorf("invalid JSON content: %w", err)
		}
		var extra any
		if err := decoder.Decode(&extra); err != io.EOF {
			return Body{}, fmt.Errorf("invalid JSON content after the first value")
		}
		content, err := normalizeJSONUnicode(materializeJSONNumbers(value))
		if err != nil {
			return Body{}, fmt.Errorf("normalize JSON content: %w", err)
		}
		return Body{Type: bodyType, Content: content}, nil
	case BodyTypeText:
		return Body{Type: bodyType, Content: norm.NFC.String(*content)}, nil
	case BodyTypeBinary:
		value, err := hex.DecodeString(*content)
		if err != nil {
			return Body{}, fmt.Errorf("invalid binary content: %w", err)
		}
		return Body{Type: bodyType, Content: value}, nil
	default:
		return Body{}, fmt.Errorf("unsupported body type: %s", bodyType)
	}
}

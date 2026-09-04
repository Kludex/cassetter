package cassetter

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"

	"gopkg.in/yaml.v3"
)

func decodeYAMLBody(node *yaml.Node) (Body, error) {
	if node.Kind == yaml.AliasNode {
		return decodeYAMLBody(node.Alias)
	}
	if node.Kind == yaml.ScalarNode {
		return decodeYAMLBodyScalar(node)
	}
	if node.Kind != yaml.MappingNode {
		return Body{}, fmt.Errorf("body must be a string, mapping, or null")
	}
	typeNode, hasType := mappingValue(node, "type")
	contentNode, hasContent := mappingValue(node, "content")
	if hasType && typeNode.Tag == "!!str" && knownBodyType(BodyType(typeNode.Value)) && onlyBodyEnvelopeKeys(node) {
		if !hasContent || contentNode.Tag == "!!null" {
			return Body{Type: BodyTypeNone}, nil
		}
		return decodeYAMLBodyEnvelope(BodyType(typeNode.Value), contentNode)
	}
	if stringNode, found := mappingValue(node, "string"); found {
		return decodeYAMLBodyScalar(stringNode)
	}
	value, err := decodeYAMLJSONValue(node)
	if err != nil {
		return Body{}, err
	}
	normalized, err := normalizeJSONValue(value)
	if err != nil {
		return Body{}, fmt.Errorf("JSON body content: %w", err)
	}
	return Body{Type: BodyTypeJSON, Content: normalized}, nil
}

func decodeYAMLBodyScalar(node *yaml.Node) (Body, error) {
	if node.Tag == "!!null" || node.Tag != "!!str" && node.Tag != "!!binary" {
		return Body{Type: BodyTypeNone}, nil
	}
	var content string
	if err := node.Decode(&content); err != nil {
		return Body{}, err
	}
	if node.Tag == "!!binary" {
		return Body{Type: BodyTypeBinary, Content: []byte(content)}, nil
	}
	if content == "" {
		return Body{Type: BodyTypeNone}, nil
	}
	decoder := json.NewDecoder(bytes.NewBufferString(content))
	decoder.UseNumber()
	var value any
	if decoder.Decode(&value) == nil {
		var extra any
		if decoder.Decode(&extra) == io.EOF {
			return Body{Type: BodyTypeJSON, Content: materializeJSONNumbers(value)}, nil
		}
	}
	return Body{Type: BodyTypeText, Content: content}, nil
}

func decodeYAMLBodyEnvelope(bodyType BodyType, contentNode *yaml.Node) (Body, error) {
	switch bodyType {
	case BodyTypeJSON:
		value, err := decodeYAMLJSONValue(contentNode)
		if err != nil {
			return Body{}, err
		}
		normalized, err := normalizeJSONValue(value)
		if err != nil {
			return Body{}, fmt.Errorf("JSON body content: %w", err)
		}
		return Body{Type: bodyType, Content: normalized}, nil
	case BodyTypeText:
		var content string
		if contentNode.Tag != "!!str" || contentNode.Decode(&content) != nil {
			return Body{}, fmt.Errorf("text body content must be a string")
		}
		return Body{Type: bodyType, Content: content}, nil
	case BodyTypeBinary:
		var content string
		if contentNode.Tag != "!!str" || contentNode.Decode(&content) != nil {
			return Body{}, fmt.Errorf("binary body content must be a hexadecimal string")
		}
		value, err := hex.DecodeString(content)
		if err != nil {
			return Body{}, fmt.Errorf("decode binary body: %w", err)
		}
		return Body{Type: bodyType, Content: value}, nil
	case BodyTypeNone:
		return Body{Type: bodyType}, nil
	default:
		return Body{}, fmt.Errorf("unknown body type %q", bodyType)
	}
}

func knownBodyType(bodyType BodyType) bool {
	return bodyType == BodyTypeJSON || bodyType == BodyTypeText || bodyType == BodyTypeBinary || bodyType == BodyTypeNone
}

func onlyBodyEnvelopeKeys(node *yaml.Node) bool {
	for index := 0; index+1 < len(node.Content); index += 2 {
		if node.Content[index].Value != "type" && node.Content[index].Value != "content" {
			return false
		}
	}
	return true
}

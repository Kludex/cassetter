package cassetter

import (
	"encoding/json"
	"fmt"
	"math"
	"strconv"
	"strings"

	"gopkg.in/yaml.v3"
)

type yamlJSONValue struct {
	value any
}

func (value yamlJSONValue) MarshalYAML() (any, error) {
	content, err := json.Marshal(value.value)
	if err != nil {
		return nil, err
	}
	var document yaml.Node
	if err := yaml.Unmarshal(content, &document); err != nil {
		return nil, err
	}
	return document.Content[0], nil
}

func decodeYAMLJSONValue(node *yaml.Node) (any, error) {
	if node.Kind == yaml.AliasNode {
		return decodeYAMLJSONValue(node.Alias)
	}
	switch node.Kind {
	case yaml.MappingNode:
		value := make(map[string]any, len(node.Content)/2)
		for index := 0; index+1 < len(node.Content); index += 2 {
			key := node.Content[index].Value
			child, err := decodeYAMLJSONValue(node.Content[index+1])
			if err != nil {
				return nil, err
			}
			value[key] = child
		}
		return value, nil
	case yaml.SequenceNode:
		value := make([]any, len(node.Content))
		for index, childNode := range node.Content {
			child, err := decodeYAMLJSONValue(childNode)
			if err != nil {
				return nil, err
			}
			value[index] = child
		}
		return value, nil
	case yaml.ScalarNode:
		switch node.Tag {
		case "!!null":
			return nil, nil
		case "!!str", "!!timestamp":
			return node.Value, nil
		case "!!bool":
			return strconv.ParseBool(node.Value)
		case "!!int":
			if value, err := strconv.ParseInt(node.Value, 0, 64); err == nil {
				return value, nil
			}
			if value, err := strconv.ParseUint(node.Value, 0, 64); err == nil {
				return value, nil
			}
			return json.Number(node.Value), nil
		case "!!float":
			if isDecimalInteger(node.Value) {
				return json.Number(node.Value), nil
			}
			value, err := strconv.ParseFloat(node.Value, 64)
			if err != nil || math.IsInf(value, 0) || math.IsNaN(value) {
				return nil, fmt.Errorf("invalid JSON number %q", node.Value)
			}
			return value, nil
		default:
			return nil, fmt.Errorf("unsupported JSON scalar %q", node.Tag)
		}
	default:
		return nil, fmt.Errorf("unsupported YAML node in JSON body")
	}
}

func isDecimalInteger(value string) bool {
	value = strings.TrimPrefix(strings.TrimPrefix(value, "+"), "-")
	if value == "" {
		return false
	}
	for _, character := range value {
		if character < '0' || character > '9' {
			return false
		}
	}
	return true
}

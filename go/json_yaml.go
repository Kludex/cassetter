package cassetter

import (
	"bytes"
	"encoding/json"
	"fmt"
	"sort"
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
	decoder := json.NewDecoder(bytes.NewReader(content))
	decoder.UseNumber()
	var canonical any
	if err := decoder.Decode(&canonical); err != nil {
		return nil, err
	}
	return encodeYAMLJSONValue(canonical)
}

func encodeYAMLJSONValue(value any) (*yaml.Node, error) {
	switch typed := value.(type) {
	case nil:
		return &yaml.Node{Kind: yaml.ScalarNode, Tag: "!!null", Value: "null"}, nil
	case bool:
		return &yaml.Node{Kind: yaml.ScalarNode, Tag: "!!bool", Value: strconv.FormatBool(typed)}, nil
	case json.Number:
		if _, err := json.Marshal(typed); err != nil {
			return nil, err
		}
		tag := "!!int"
		if strings.ContainsAny(string(typed), ".eE") {
			tag = "!!float"
		}
		return &yaml.Node{Kind: yaml.ScalarNode, Tag: tag, Value: string(typed)}, nil
	case string:
		node := &yaml.Node{Kind: yaml.ScalarNode, Tag: "!!str", Value: typed}
		if strings.Contains(typed, "\n") && strings.Trim(typed, "\n \t") == "" {
			node.Style = yaml.DoubleQuotedStyle
		}
		return node, nil
	case []any:
		node := &yaml.Node{Kind: yaml.SequenceNode, Tag: "!!seq"}
		for _, child := range typed {
			childNode, err := encodeYAMLJSONValue(child)
			if err != nil {
				return nil, err
			}
			node.Content = append(node.Content, childNode)
		}
		return node, nil
	case map[string]any:
		node := &yaml.Node{Kind: yaml.MappingNode, Tag: "!!map"}
		keys := make([]string, 0, len(typed))
		for key := range typed {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		for _, key := range keys {
			childNode, err := encodeYAMLJSONValue(typed[key])
			if err != nil {
				return nil, err
			}
			node.Content = append(node.Content, &yaml.Node{Kind: yaml.ScalarNode, Tag: "!!str", Value: key}, childNode)
		}
		return node, nil
	default:
		return nil, fmt.Errorf("unsupported JSON value %T", value)
	}
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
			return validatedJSONNumber(node.Value)
		case "!!float":
			return validatedJSONNumber(node.Value)
		default:
			return nil, fmt.Errorf("unsupported JSON scalar %q", node.Tag)
		}
	default:
		return nil, fmt.Errorf("unsupported YAML node in JSON body")
	}
}

func validatedJSONNumber(value string) (json.Number, error) {
	number := json.Number(value)
	if _, err := json.Marshal(number); err != nil {
		return "", fmt.Errorf("invalid JSON number %q", value)
	}
	return number, nil
}

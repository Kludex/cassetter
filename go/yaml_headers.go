package cassetter

import (
	"fmt"
	"net/http"
	"strings"

	"gopkg.in/yaml.v3"
)

type yamlHeaders http.Header

func (headers *yamlHeaders) UnmarshalYAML(node *yaml.Node) error {
	if node.Tag == "!!null" {
		*headers = yamlHeaders{}
		return nil
	}
	if node.Kind != yaml.MappingNode {
		return fmt.Errorf("headers must be a mapping")
	}
	result := make(http.Header, len(node.Content)/2)
	for index := 0; index+1 < len(node.Content); index += 2 {
		name := node.Content[index].Value
		valueNode := node.Content[index+1]
		values := make([]string, 0, 1)
		if valueNode.Kind == yaml.SequenceNode {
			for _, item := range valueNode.Content {
				if value, ok := yamlHeaderValue(item); ok {
					values = append(values, value)
				}
			}
		} else if value, ok := yamlHeaderValue(valueNode); ok {
			values = append(values, value)
		}
		result[name] = values
	}
	*headers = yamlHeaders(result)
	return nil
}

func yamlHeaderValue(node *yaml.Node) (string, bool) {
	if node.Kind != yaml.ScalarNode || node.Tag == "!!null" {
		return "", false
	}
	if node.Tag == "!!str" || node.Tag == "!!binary" {
		var value string
		if node.Decode(&value) != nil {
			return "", false
		}
		if node.Tag == "!!binary" {
			value = strings.ToValidUTF8(value, "�")
		}
		return value, true
	}
	switch node.Tag {
	case "!!bool", "!!int", "!!float":
		return node.Value, true
	default:
		return "", false
	}
}

package cassetter

import (
	"fmt"
	"net/http"

	"gopkg.in/yaml.v3"
)

// UnmarshalYAML reads cassetter and VCR.py request representations.
func (r *HTTPRequest) UnmarshalYAML(node *yaml.Node) error {
	var value struct {
		Method  string      `yaml:"method"`
		URI     string      `yaml:"uri"`
		Headers yamlHeaders `yaml:"headers"`
		Body    Body        `yaml:"body"`
	}
	if err := node.Decode(&value); err != nil {
		return err
	}
	body, found, err := parsedYAMLBody(node)
	if err != nil {
		return err
	}
	if found {
		value.Body = body
	}
	if value.Body.Type == "" {
		value.Body.Type = BodyTypeNone
	}
	headers := http.Header(value.Headers)
	if headers == nil {
		headers = make(http.Header)
	}
	*r = HTTPRequest{Method: value.Method, URI: value.URI, Headers: headers, Body: value.Body}
	return nil
}

// UnmarshalYAML reads cassetter and VCR.py response representations.
func (r *HTTPResponse) UnmarshalYAML(node *yaml.Node) error {
	var value struct {
		Headers yamlHeaders `yaml:"headers"`
		Body    Body        `yaml:"body"`
	}
	if err := node.Decode(&value); err != nil {
		return err
	}
	statusNode, found := mappingValue(node, "status")
	if !found || statusNode.Tag == "!!null" {
		return fmt.Errorf("HTTP response status is required")
	}
	if statusNode.Kind == yaml.MappingNode {
		statusNode, found = mappingValue(statusNode, "code")
		if !found || statusNode.Tag == "!!null" {
			return fmt.Errorf("VCR status is missing its code")
		}
	}
	if statusNode.Kind != yaml.ScalarNode || statusNode.Tag != "!!int" {
		return fmt.Errorf("HTTP response status must be an integer or VCR status mapping")
	}
	var status int
	if err := statusNode.Decode(&status); err != nil {
		return err
	}
	body, hasParsedBody, err := parsedYAMLBody(node)
	if err != nil {
		return err
	}
	if hasParsedBody {
		value.Body = body
	}
	if value.Body.Type == "" {
		value.Body.Type = BodyTypeNone
	}
	headers := http.Header(value.Headers)
	if headers == nil {
		headers = make(http.Header)
	}
	*r = HTTPResponse{Status: status, Headers: headers, Body: value.Body}
	return nil
}

func parsedYAMLBody(node *yaml.Node) (Body, bool, error) {
	parsedBodyNode, found := mappingValue(node, "parsed_body")
	if !found || parsedBodyNode.Tag == "!!null" {
		return Body{}, false, nil
	}
	value, err := decodeYAMLJSONValue(parsedBodyNode)
	if err != nil {
		return Body{}, false, err
	}
	normalized, err := normalizeJSONValue(value)
	if err != nil {
		return Body{}, false, fmt.Errorf("parsed_body must contain JSON-compatible data: %w", err)
	}
	return Body{Type: BodyTypeJSON, Content: normalizeJSONUnicode(normalized)}, true, nil
}

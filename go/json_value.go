package cassetter

import (
	"encoding/json"
	"fmt"
)

func validateJSONDebug(value any) error {
	_, err := normalizeJSONDebug(value)
	return err
}

func normalizeJSONDebug(value any) (any, error) {
	normalized, err := normalizeJSONValue(value)
	if err != nil {
		return nil, fmt.Errorf("gRPC json_debug must contain JSON-compatible data: %w", err)
	}
	return normalized, nil
}

func normalizeJSONValue(value any) (any, error) {
	normalized := normalizeJSONValueContent(value)
	if _, err := json.Marshal(normalized); err != nil {
		return nil, err
	}
	return normalized, nil
}

func normalizeJSONValueContent(value any) any {
	switch typed := value.(type) {
	case map[any]any:
		object := make(map[string]any, len(typed))
		for key, child := range typed {
			keyString, ok := key.(string)
			if !ok {
				keyString = fmt.Sprint(key)
			}
			object[keyString] = normalizeJSONValueContent(child)
		}
		return object
	case map[string]any:
		object := make(map[string]any, len(typed))
		for key, child := range typed {
			object[key] = normalizeJSONValueContent(child)
		}
		return object
	case []any:
		array := make([]any, len(typed))
		for index, child := range typed {
			array[index] = normalizeJSONValueContent(child)
		}
		return array
	default:
		return value
	}
}

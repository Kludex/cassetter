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
	normalized := normalizeJSONDebugValue(value)
	if _, err := json.Marshal(normalized); err != nil {
		return nil, fmt.Errorf("gRPC json_debug must contain JSON-compatible data: %w", err)
	}
	return normalized, nil
}

func normalizeJSONDebugValue(value any) any {
	switch typed := value.(type) {
	case map[any]any:
		object := make(map[string]any, len(typed))
		for key, child := range typed {
			keyString, ok := key.(string)
			if !ok {
				keyString = fmt.Sprint(key)
			}
			object[keyString] = normalizeJSONDebugValue(child)
		}
		return object
	case map[string]any:
		object := make(map[string]any, len(typed))
		for key, child := range typed {
			object[key] = normalizeJSONDebugValue(child)
		}
		return object
	case []any:
		array := make([]any, len(typed))
		for index, child := range typed {
			array[index] = normalizeJSONDebugValue(child)
		}
		return array
	default:
		return value
	}
}

package cassetter

import (
	"fmt"
	"sort"

	"golang.org/x/text/unicode/norm"
)

func normalizeJSONUnicode(value any) (any, error) {
	switch typed := value.(type) {
	case string:
		return norm.NFC.String(typed), nil
	case map[string]any:
		keys := make([]string, 0, len(typed))
		for key := range typed {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		normalized := make(map[string]any, len(typed))
		originalKeys := make(map[string]string, len(typed))
		for _, key := range keys {
			normalizedKey := norm.NFC.String(key)
			if original, exists := originalKeys[normalizedKey]; exists && original != key {
				return nil, fmt.Errorf("JSON keys %q and %q normalize to %q", original, key, normalizedKey)
			}
			child, err := normalizeJSONUnicode(typed[key])
			if err != nil {
				return nil, err
			}
			originalKeys[normalizedKey] = key
			normalized[normalizedKey] = child
		}
		return normalized, nil
	case []any:
		normalized := make([]any, len(typed))
		for index, child := range typed {
			normalizedChild, err := normalizeJSONUnicode(child)
			if err != nil {
				return nil, err
			}
			normalized[index] = normalizedChild
		}
		return normalized, nil
	default:
		return value, nil
	}
}

package cassetter

import (
	"sort"

	"golang.org/x/text/unicode/norm"
)

func normalizeJSONUnicode(value any) any {
	switch typed := value.(type) {
	case string:
		return norm.NFC.String(typed)
	case map[string]any:
		keys := make([]string, 0, len(typed))
		for key := range typed {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		normalized := make(map[string]any, len(typed))
		for _, key := range keys {
			normalized[norm.NFC.String(key)] = normalizeJSONUnicode(typed[key])
		}
		return normalized
	case []any:
		normalized := make([]any, len(typed))
		for index, child := range typed {
			normalized[index] = normalizeJSONUnicode(child)
		}
		return normalized
	default:
		return value
	}
}

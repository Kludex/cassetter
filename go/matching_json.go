package cassetter

import (
	"bytes"
	"encoding/json"
	"fmt"
	"slices"
)

func filteredJSON(value any, ignored []string) ([]byte, bool) {
	content, err := json.Marshal(value)
	if err != nil {
		return nil, false
	}
	var normalized any
	decoder := json.NewDecoder(bytes.NewReader(content))
	decoder.UseNumber()
	if decoder.Decode(&normalized) != nil {
		return nil, false
	}
	content, err = json.Marshal(filterJSONPaths(normalized, ignored, ""))
	return content, err == nil
}

func filterJSONPaths(value any, ignored []string, currentPath string) any {
	if slices.Contains(ignored, currentPath) {
		return nil
	}
	switch typed := value.(type) {
	case map[string]any:
		filtered := make(map[string]any, len(typed))
		for key, child := range typed {
			path := key
			if currentPath != "" {
				path = currentPath + "." + key
			}
			if !slices.Contains(ignored, path) {
				filtered[key] = filterJSONPaths(child, ignored, path)
			}
		}
		return filtered
	case []any:
		filtered := make([]any, len(typed))
		for index, child := range typed {
			path := fmt.Sprintf("%s[%d]", currentPath, index)
			filtered[index] = filterJSONPaths(child, ignored, path)
		}
		return filtered
	default:
		return value
	}
}

package cassetter

import (
	"bytes"
	"encoding/json"
	"regexp"
	"strconv"
	"strings"
)

func scrubBody(body Body, patterns []string, replacement string) Body {
	switch body.Type {
	case BodyTypeJSON:
		body.Content = scrubJSONContent(body.Content, patterns, replacement)
	case BodyTypeText:
		if text, ok := body.Content.(string); ok {
			body.Content = scrubText(text, patterns, replacement)
		}
	}
	return body
}

func scrubJSONContent(value any, patterns []string, replacement string) any {
	encoded, err := json.Marshal(value)
	if err != nil {
		return value
	}
	decoder := json.NewDecoder(bytes.NewReader(encoded))
	decoder.UseNumber()
	var normalized any
	if decoder.Decode(&normalized) != nil || !containsSecret(normalized, patterns) {
		return value
	}
	return scrubJSON(materializeJSONNumbers(normalized), patterns, replacement)
}

func materializeJSONNumbers(value any) any {
	switch typed := value.(type) {
	case json.Number:
		if integer, err := strconv.ParseInt(string(typed), 10, 64); err == nil {
			return integer
		}
		if integer, err := strconv.ParseUint(string(typed), 10, 64); err == nil {
			return integer
		}
		return typed
	case map[string]any:
		for key, child := range typed {
			typed[key] = materializeJSONNumbers(child)
		}
	case []any:
		for index, child := range typed {
			typed[index] = materializeJSONNumbers(child)
		}
	}
	return value
}

func scrubJSON(value any, patterns []string, replacement string) any {
	switch typed := value.(type) {
	case map[string]any:
		for key, child := range typed {
			if matchesPattern(key, patterns) {
				typed[key] = replacement
			} else {
				typed[key] = scrubJSON(child, patterns, replacement)
			}
		}
	case []any:
		for index, child := range typed {
			typed[index] = scrubJSON(child, patterns, replacement)
		}
	}
	return value
}

func matchesPattern(key string, patterns []string) bool {
	lower := strings.ToLower(key)
	for _, pattern := range patterns {
		if strings.Contains(lower, strings.ToLower(pattern)) {
			return true
		}
	}
	return false
}

func scrubText(text string, patterns []string, replacement string) string {
	var value any
	if json.Unmarshal([]byte(text), &value) == nil {
		if !containsSecret(value, patterns) {
			return text
		}
		scrubbed, err := json.Marshal(scrubJSON(value, patterns, replacement))
		if err == nil {
			return string(scrubbed)
		}
	}
	if strings.HasPrefix(text, "data:") || strings.Contains(text, "\ndata:") {
		lines := strings.SplitAfter(text, "\n")
		for index, line := range lines {
			newline := ""
			body := line
			if strings.HasSuffix(body, "\n") {
				newline = "\n"
				body = strings.TrimSuffix(body, "\n")
			}
			carriage := strings.HasSuffix(body, "\r")
			body = strings.TrimSuffix(body, "\r")
			if payload, found := strings.CutPrefix(body, "data:"); found {
				space := payload[:len(payload)-len(strings.TrimLeft(payload, " \t"))]
				body = "data:" + space + scrubText(strings.TrimLeft(payload, " \t"), patterns, replacement)
			}
			if carriage {
				body += "\r"
			}
			lines[index] = body + newline
		}
		return strings.Join(lines, "")
	}
	quotedReplacement, _ := json.Marshal(replacement)
	for _, pattern := range patterns {
		jsonExpression, err := regexp.Compile(
			`(?i)("[^"]*` + regexp.QuoteMeta(pattern) +
				`[^"]*"\s*:\s*)("(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)`,
		)
		if err != nil {
			continue
		}
		text = jsonExpression.ReplaceAllStringFunc(text, func(match string) string {
			parts := jsonExpression.FindStringSubmatch(match)
			return parts[1] + string(quotedReplacement)
		})
		formExpression, err := regexp.Compile(
			`(?i)([^&\s=]*` + regexp.QuoteMeta(pattern) + `[^&\s=]*=)[^&\s]*`,
		)
		if err != nil {
			continue
		}
		text = formExpression.ReplaceAllStringFunc(text, func(match string) string {
			key, _, _ := strings.Cut(match, "=")
			return key + "=" + replacement
		})
	}
	return text
}

func containsSecret(value any, patterns []string) bool {
	switch typed := value.(type) {
	case map[string]any:
		for key, child := range typed {
			if matchesPattern(key, patterns) || containsSecret(child, patterns) {
				return true
			}
		}
	case []any:
		for _, child := range typed {
			if containsSecret(child, patterns) {
				return true
			}
		}
	}
	return false
}

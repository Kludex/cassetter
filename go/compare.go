package cassetter

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"math/big"
	"path"
	"slices"
	"strings"

	"github.com/pmezard/go-difflib/difflib"
)

// Compare selects what RecordModeVerify compares between a recorded response and the live one.
// The status is always compared. Everything not listed is ignored.
type Compare struct {
	// Headers are response header names compared by value. Globs such as "x-price-*" are allowed.
	Headers []string
	// JSONIgnore are paths removed from JSON bodies before comparing, in the WithIgnoredJSONPaths syntax.
	// With SSE, they apply to each event's payload.
	JSONIgnore []string
	// SSE compares the body as the list of Server-Sent Events data payloads, so chunk boundaries do not matter.
	SSE bool
	// FloatTolerance is the largest difference between two JSON numbers that still counts as equal.
	FloatTolerance float64
}

// BeforeCompareResponse receives the recorded and the live response and returns both normalized,
// for differences Compare cannot express.
type BeforeCompareResponse func(recorded HTTPResponse, live HTTPResponse) (HTTPResponse, HTTPResponse)

// ErrResponseMismatch identifies a live response that differs from its recording in RecordModeVerify.
var ErrResponseMismatch = errors.New("live response differs from the recording")

// ResponseMismatchError describes a live response that differs from its recording.
type ResponseMismatchError struct {
	Path   string
	Method string
	URI    string
	// Diff is a unified diff of the recorded and the live response, as compared.
	Diff string
}

// Error implements error.
func (e *ResponseMismatchError) Error() string {
	return fmt.Sprintf("%s: cassette %s, %s %s\n%s", ErrResponseMismatch, e.Path, e.Method, e.URI, e.Diff)
}

// Unwrap allows errors.Is(err, ErrResponseMismatch).
func (e *ResponseMismatchError) Unwrap() error {
	return ErrResponseMismatch
}

func compareResponses(compare Compare, recorded HTTPResponse, live HTTPResponse) (string, error) {
	expected, err := normalizeResponse(compare, recorded)
	if err != nil {
		return "", err
	}
	actual, err := normalizeResponse(compare, live)
	if err != nil {
		return "", err
	}
	actual.body = tolerate(expected.body, actual.body, compare.FloatTolerance)
	left, err := expected.render()
	if err != nil {
		return "", err
	}
	right, err := actual.render()
	if err != nil {
		return "", err
	}
	if slices.Equal(left, right) {
		return "", nil
	}
	return difflib.GetUnifiedDiffString(difflib.UnifiedDiff{
		A:        left,
		B:        right,
		FromFile: "recorded",
		ToFile:   "live",
		Context:  3,
	})
}

type normalizedResponse struct {
	status   int
	headers  map[string][]string
	bodyType BodyType
	body     any
}

func normalizeResponse(compare Compare, response HTTPResponse) (normalizedResponse, error) {
	names := slices.Sorted(maps.Keys(response.Headers))
	headers := map[string][]string{}
	for _, name := range names {
		lower := strings.ToLower(name)
		if slices.ContainsFunc(compare.Headers, func(pattern string) bool {
			matched, _ := path.Match(strings.ToLower(pattern), lower)
			return matched
		}) {
			headers[lower] = append(headers[lower], response.Headers[name]...)
		}
	}
	bodyType := response.Body.Type
	if bodyType == "" {
		bodyType = BodyTypeNone
	}
	normalized := normalizedResponse{
		status:   response.Status,
		headers:  headers,
		bodyType: bodyType,
		body:     response.Body.Content,
	}
	switch {
	case response.Body.Type == BodyTypeJSON:
		value, err := canonicalJSON(response.Body.Content)
		if err != nil {
			return normalizedResponse{}, err
		}
		normalized.body = filterJSONPaths(value, compare.JSONIgnore, "")
	case compare.SSE && response.Body.Type == BodyTypeText:
		text, _ := response.Body.Content.(string)
		events := []any{}
		for block := range strings.SplitSeq(strings.ReplaceAll(text, "\r\n", "\n"), "\n\n") {
			var lines []string
			for line := range strings.SplitSeq(block, "\n") {
				if data, ok := strings.CutPrefix(line, "data:"); ok {
					lines = append(lines, strings.TrimPrefix(data, " "))
				}
			}
			if lines == nil {
				continue
			}
			data := strings.Join(lines, "\n")
			var event any = data
			if value, err := decodeJSON([]byte(data)); err == nil {
				event = filterJSONPaths(value, compare.JSONIgnore, "")
			}
			events = append(events, event)
		}
		normalized.body = events
	}
	return normalized, nil
}

func (r normalizedResponse) render() ([]string, error) {
	lines := []string{fmt.Sprintf("status: %d\n", r.status), "@@ headers @@\n"}
	for _, name := range slices.Sorted(maps.Keys(r.headers)) {
		for _, value := range r.headers[name] {
			lines = append(lines, name+": "+value+"\n")
		}
	}
	lines = append(lines, fmt.Sprintf("@@ %s body @@\n", r.bodyType))
	if r.bodyType != BodyTypeJSON {
		switch body := r.body.(type) {
		case []byte:
			return append(lines, fmt.Sprintf("%q\n", body)), nil
		case string:
			for line := range strings.SplitSeq(body, "\n") {
				lines = append(lines, line+"\n")
			}
			return lines, nil
		}
	}
	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(r.body); err != nil {
		return nil, fmt.Errorf("render response body: %w", err)
	}
	return append(lines, difflib.SplitLines(strings.TrimSuffix(buffer.String(), "\n"))...), nil
}

func canonicalJSON(value any) (any, error) {
	content, err := json.Marshal(normalizeJSONValueContent(value))
	if err != nil {
		return nil, fmt.Errorf("compare JSON body: %w", err)
	}
	return decodeJSON(content)
}

func decodeJSON(content []byte) (any, error) {
	var value any
	decoder := json.NewDecoder(bytes.NewReader(content))
	decoder.UseNumber()
	if err := decoder.Decode(&value); err != nil {
		return nil, err
	}
	if decoder.More() {
		return nil, errors.New("unexpected data after JSON value")
	}
	return value, nil
}

// tolerate returns live with numbers within tolerance of their recording replaced by it, so they drop out of the diff.
func tolerate(recorded any, live any, tolerance float64) any {
	switch typed := live.(type) {
	case map[string]any:
		object, ok := recorded.(map[string]any)
		if !ok {
			return live
		}
		result := make(map[string]any, len(typed))
		for key, value := range typed {
			if expected, found := object[key]; found {
				value = tolerate(expected, value, tolerance)
			}
			result[key] = value
		}
		return result
	case []any:
		array, ok := recorded.([]any)
		if !ok {
			return live
		}
		result := slices.Clone(typed)
		for index := range min(len(array), len(result)) {
			result[index] = tolerate(array[index], result[index], tolerance)
		}
		return result
	case json.Number:
		expected, ok := recorded.(json.Number)
		if !ok {
			return live
		}
		left, leftOK := new(big.Rat).SetString(string(expected))
		right, rightOK := new(big.Rat).SetString(string(typed))
		limit := new(big.Rat).SetFloat64(tolerance)
		if leftOK && rightOK && limit != nil && new(big.Rat).Abs(new(big.Rat).Sub(left, right)).Cmp(limit) <= 0 {
			return expected
		}
	}
	return live
}

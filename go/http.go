package cassetter

import (
	"bytes"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
)

func closeRequestBody(request *http.Request) error {
	if request.Body == nil {
		return nil
	}
	return request.Body.Close()
}

func replayResponse(request *http.Request, recorded HTTPResponse) (*http.Response, error) {
	content, err := bodyBytes(recorded.Body)
	if err != nil {
		return nil, fmt.Errorf("replay response: %w", err)
	}
	headers := replayHeaders(recorded.Headers)
	contentLength := int64(len(content))
	if values, found := findHeader(headers, "content-length"); found && len(values) > 0 {
		if len(content) > 0 {
			headers.Set("Content-Length", strconv.Itoa(len(content)))
		} else if recordedLength, parseErr := strconv.ParseInt(values[0], 10, 64); parseErr == nil {
			contentLength = recordedLength
		}
	}
	statusText := http.StatusText(recorded.Status)
	status := strconv.Itoa(recorded.Status)
	if statusText != "" {
		status += " " + statusText
	}
	return &http.Response{
		Status:        status,
		StatusCode:    recorded.Status,
		Proto:         "HTTP/1.1",
		ProtoMajor:    1,
		ProtoMinor:    1,
		Header:        headers,
		Body:          io.NopCloser(bytes.NewReader(content)),
		ContentLength: contentLength,
		Request:       request,
	}, nil
}

func recordHeaders(headers http.Header) http.Header {
	result := make(http.Header, len(headers))
	for name, values := range headers {
		lower := strings.ToLower(name)
		result[lower] = append(result[lower], values...)
	}
	return result
}

func replayHeaders(headers http.Header) http.Header {
	result := make(http.Header, len(headers))
	for name, values := range headers {
		for _, value := range values {
			result.Add(name, value)
		}
	}
	return result
}

func headerValue(headers http.Header, name string) string {
	values, _ := findHeader(headers, name)
	if len(values) == 0 {
		return ""
	}
	return values[0]
}

func findHeader(headers http.Header, name string) ([]string, bool) {
	for candidate, values := range headers {
		if strings.EqualFold(candidate, name) {
			return values, true
		}
	}
	return nil, false
}

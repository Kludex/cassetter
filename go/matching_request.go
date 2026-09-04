package cassetter

import (
	"bytes"
	"errors"
	"io"
	"net/http"
	"slices"
)

func (t *Transport) requestForMatching(request *http.Request) (HTTPRequest, error) {
	headers := recordHeaders(request.Header)
	body := Body{Type: BodyTypeNone}
	if t.matchesRequestContent() {
		content, err := readRequestBody(request)
		if err != nil {
			return HTTPRequest{}, err
		}
		content, err = decodeBody(content, headers)
		if err != nil {
			return HTTPRequest{}, err
		}
		body, err = bodyFromBytes(content, headerValue(headers, "content-type"))
		if err != nil {
			return HTTPRequest{}, err
		}
	}
	probe := HTTPRequest{
		Method:  request.Method,
		URI:     scrubURI(request.URL.String(), t.config.security.FilterQueryParameters, t.config.security.Replacement),
		Headers: headers,
		Body:    body,
	}
	filterHeaders(probe.Headers, t.config.security.FilterHeaders)
	probe.Body = scrubBody(probe.Body, t.config.security.BodyScrubPatterns, t.config.security.Replacement)
	retagContentLength(probe.Headers, probe.Body)
	return t.matchingRequest(probe), nil
}

func (t *Transport) matchesRequestContent() bool {
	return slices.Contains(t.config.matchers, MatcherBody) || slices.Contains(t.config.matchers, MatcherJSONBody)
}

func readRequestBody(request *http.Request) ([]byte, error) {
	if request.Body == nil || request.Body == http.NoBody {
		return nil, nil
	}
	if request.GetBody != nil {
		body, err := request.GetBody()
		if err != nil {
			return nil, err
		}
		content, readErr := readCapped(body)
		return content, errors.Join(readErr, body.Close())
	}
	content, readErr := readCapped(request.Body)
	closeErr := request.Body.Close()
	request.Body = io.NopCloser(bytes.NewReader(content))
	return content, errors.Join(readErr, closeErr)
}

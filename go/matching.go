package cassetter

import (
	"bytes"
	"errors"
	"fmt"
	"net/http"
	"slices"
	"strings"
)

// Matcher identifies a recorded request field used for playback matching.
type Matcher string

const (
	// MatcherMethod compares HTTP methods case-insensitively.
	MatcherMethod Matcher = "method"
	// MatcherURI compares request URIs.
	MatcherURI Matcher = "uri"
	// MatcherHeaders requires every recorded header in the incoming request.
	MatcherHeaders Matcher = "headers"
	// MatcherBody compares typed request bodies.
	MatcherBody Matcher = "body"
	// MatcherJSONBody compares JSON bodies after removing ignored paths.
	MatcherJSONBody Matcher = "json_body"
)

func (t *Transport) usesMethodURIIndex() bool {
	return slices.Contains(t.config.matchers, MatcherMethod) && slices.Contains(t.config.matchers, MatcherURI)
}

func (t *Transport) normalizeURI(uri string) string {
	if t.config.uriNormalizer == nil {
		return uri
	}
	return t.config.uriNormalizer(uri)
}

func (t *Transport) matchingRequest(request HTTPRequest) HTTPRequest {
	if slices.Contains(t.config.matchers, MatcherURI) {
		request.URI = t.normalizeURI(request.URI)
	}
	return request
}

func validateMatchers(matchers []Matcher) error {
	if len(matchers) == 0 {
		return errors.New("cassetter: at least one request matcher is required")
	}
	for _, matcher := range matchers {
		switch matcher {
		case MatcherMethod, MatcherURI, MatcherHeaders, MatcherBody, MatcherJSONBody:
		default:
			return fmt.Errorf("cassetter: unknown request matcher %q", matcher)
		}
	}
	return nil
}

func matchesRequest(incoming HTTPRequest, recorded HTTPRequest, config transportConfig) bool {
	for _, matcher := range config.matchers {
		var matched bool
		switch matcher {
		case MatcherMethod:
			matched = strings.EqualFold(incoming.Method, recorded.Method)
		case MatcherURI:
			matched = incoming.URI == recorded.URI
		case MatcherHeaders:
			matched = matchHeaders(incoming.Headers, recorded.Headers)
		case MatcherBody:
			matched = matchBody(incoming.Body, recorded.Body)
		case MatcherJSONBody:
			matched = matchJSONBody(incoming.Body, recorded.Body, config.ignoreJSONPaths)
		}
		if !matched {
			return false
		}
	}
	return true
}

func matchHeaders(incoming http.Header, recorded http.Header) bool {
	for name, values := range recorded {
		incomingValues, found := findHeader(incoming, name)
		if !found || !slices.Equal(incomingValues, values) {
			return false
		}
	}
	return true
}

func matchBody(incoming Body, recorded Body) bool {
	incomingType := incoming.Type
	if incomingType == "" {
		incomingType = BodyTypeNone
	}
	recordedType := recorded.Type
	if recordedType == "" {
		recordedType = BodyTypeNone
	}
	if incomingType != recordedType {
		return false
	}
	incomingContent, incomingErr := bodyBytes(incoming)
	recordedContent, recordedErr := bodyBytes(recorded)
	return incomingErr == nil && recordedErr == nil && bytes.Equal(incomingContent, recordedContent)
}

func matchJSONBody(incoming Body, recorded Body, ignored []string) bool {
	if incoming.Type != BodyTypeJSON || recorded.Type != BodyTypeJSON {
		return matchBody(incoming, recorded)
	}
	incomingContent, incomingOK := filteredJSON(incoming.Content, ignored)
	recordedContent, recordedOK := filteredJSON(recorded.Content, ignored)
	return incomingOK && recordedOK && bytes.Equal(incomingContent, recordedContent)
}

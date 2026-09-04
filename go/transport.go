package cassetter

import (
	"errors"
	"net/http"
	"sync"
	"time"
)

// Transport records and replays HTTP exchanges through an http.RoundTripper.
type Transport struct {
	base   http.RoundTripper
	config transportConfig

	initialize sync.Once
	initErr    error
	mu         sync.Mutex
	cassette   *Cassette
	played     []bool
	index      map[string][]int
	orders     []uint64
	nextOrder  uint64
	canRecord  bool
}

// CloseIdleConnections closes idle connections held by the wrapped transport.
func (t *Transport) CloseIdleConnections() {
	if closer, ok := t.base.(interface{ CloseIdleConnections() }); ok {
		closer.CloseIdleConnections()
	}
}

// RoundTrip implements http.RoundTripper.
func (t *Transport) RoundTrip(request *http.Request) (*http.Response, error) {
	t.initialize.Do(t.load)
	if t.initErr != nil {
		return nil, errors.Join(t.initErr, closeRequestBody(request))
	}
	uri := request.URL.String()
	matchURI := scrubURI(uri, t.config.security.FilterQueryParameters, t.config.security.Replacement)
	if t.config.mode != RecordModeAll && t.config.mode != RecordModeRewrite {
		interaction, found := t.takeMatch(request.Method, matchURI)
		if found {
			if err := closeRequestBody(request); err != nil {
				return nil, err
			}
			return replayResponse(request, interaction.Response)
		}
	}
	if !t.canRecord {
		return nil, errors.Join(&NoMatchError{Method: request.Method, URI: uri}, closeRequestBody(request))
	}

	order := t.reserveOrder()
	outgoing := request.Clone(request.Context())
	requestBody := newRequestBody(outgoing.Body)
	if outgoing.Body != nil {
		outgoing.Body = requestBody
	}
	requestHeaders := recordHeaders(request.Header)
	requestMethod := request.Method
	response, err := t.base.RoundTrip(outgoing)
	if err != nil {
		return nil, err
	}
	responseHeaders := recordHeaders(response.Header)
	responseStatus := response.StatusCode
	finalize := func(content []byte) error {
		requestContent, err := decodeBody(requestBody.content(), requestHeaders)
		if err != nil {
			return err
		}
		responseContent, err := decodeBody(content, responseHeaders)
		if err != nil {
			return err
		}
		interaction := HTTPInteraction{
			Request: HTTPRequest{
				Method:  requestMethod,
				URI:     uri,
				Headers: requestHeaders,
				Body:    bodyFromBytes(requestContent, headerValue(requestHeaders, "content-type")),
			},
			Response: HTTPResponse{
				Status:  responseStatus,
				Headers: responseHeaders,
				Body:    bodyFromBytes(responseContent, headerValue(responseHeaders, "content-type")),
			},
			RecordedAt: time.Now().UTC().Format(time.RFC3339Nano),
		}
		return t.record(interaction, order)
	}
	if response.Body == nil || response.Body == http.NoBody {
		if err := finalize(nil); err != nil {
			return nil, err
		}
		response.Body = http.NoBody
		return response, nil
	}
	response.Body = newRecordingBody(response.Body, response.ContentLength, finalize)
	return response, nil
}

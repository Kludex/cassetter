package cassetter

import (
	"errors"
	"fmt"
	"net/http"
	"reflect"
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
	pending    map[uint64]pendingRecording
	recordErr  error
	closed     bool
	closeErr   error
}

type pendingRecording struct {
	method string
	uri    string
}

// CloseIdleConnections closes idle connections held by the wrapped transport.
func (t *Transport) CloseIdleConnections() {
	if closer, ok := t.base.(interface{ CloseIdleConnections() }); ok {
		closer.CloseIdleConnections()
	}
}

// RoundTrip implements http.RoundTripper.
func (t *Transport) RoundTrip(request *http.Request) (*http.Response, error) {
	if err := t.Initialize(); err != nil {
		return nil, errors.Join(err, closeRequestBody(request))
	}
	if err := t.checkOpen(); err != nil {
		return nil, errors.Join(err, closeRequestBody(request))
	}
	if request.URL == nil {
		return nil, errors.Join(errors.New("cassetter request URL is nil"), closeRequestBody(request))
	}
	request = request.Clone(request.Context())
	if t.shouldBypass(request.URL) {
		return t.base.RoundTrip(request)
	}
	if t.config.requestHook != nil {
		originalBody := request.Body
		err := t.config.requestHook(request)
		sameBody := originalBody == nil && request.Body == nil
		if originalBody != nil && request.Body != nil {
			left := reflect.ValueOf(originalBody)
			right := reflect.ValueOf(request.Body)
			sameBody = left.Type() == right.Type() && left.Comparable() && left.Equal(right)
		}
		if !sameBody {
			request.GetBody = nil
		}
		if err != nil {
			if errors.Is(err, ErrSkipRecording) {
				return t.base.RoundTrip(request)
			}
			return nil, errors.Join(fmt.Errorf("cassetter request hook: %w", err), closeRequestBody(request))
		}
	}
	if request.URL == nil {
		return nil, errors.Join(errors.New("cassetter request hook removed the request URL"), closeRequestBody(request))
	}
	uri := request.URL.String()
	if t.config.mode != RecordModeAll && t.config.mode != RecordModeRewrite {
		probe, err := t.requestForMatching(request)
		if err != nil {
			return nil, errors.Join(err, closeRequestBody(request))
		}
		interaction, found, err := t.takeMatch(probe)
		if err != nil {
			return nil, errors.Join(err, closeRequestBody(request))
		}
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

	order, err := t.reserveRecording(request.Method, uri)
	if err != nil {
		return nil, errors.Join(err, closeRequestBody(request))
	}
	outgoing := request.Clone(request.Context())
	requestBody := newRequestBody(outgoing.Body)
	if outgoing.Body != nil {
		outgoing.Body = requestBody
	}
	requestHeaders := recordHeaders(request.Header)
	requestMethod := request.Method
	response, err := t.base.RoundTrip(outgoing)
	if err != nil {
		t.finishRecording(order, nil)
		return nil, err
	}
	if response == nil {
		t.finishRecording(order, nil)
		return nil, errors.New("cassetter base transport returned a nil response")
	}
	if t.config.responseHook != nil {
		if err := t.config.responseHook(response); err != nil {
			t.finishRecording(order, nil)
			if errors.Is(err, ErrSkipRecording) {
				return response, nil
			}
			var closeErr error
			if response.Body != nil {
				closeErr = response.Body.Close()
			}
			return nil, errors.Join(fmt.Errorf("cassetter response hook: %w", err), closeErr)
		}
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
		err := finalize(nil)
		t.finishRecording(order, err)
		if err != nil {
			return nil, err
		}
		response.Body = http.NoBody
		return response, nil
	}
	incomplete := &IncompleteRecordingError{Method: requestMethod, URI: uri}
	response.Body = newRecordingBody(
		response.Body,
		response.ContentLength,
		finalize,
		incomplete,
		func(err error) { t.finishRecording(order, err) },
	)
	return response, nil
}

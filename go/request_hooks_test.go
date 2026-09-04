package cassetter_test

import (
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/Kludex/cassetter/go"
)

func TestRequestHookModifiesRequestsBeforeMatching(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	cassette := &cassetter.Cassette{
		Version: 1,
		Interactions: []cassetter.HTTPInteraction{{
			Request: cassetter.HTTPRequest{
				Method:  http.MethodPost,
				URI:     "https://example.com/hooked",
				Headers: http.Header{"content-type": {"application/json"}, "x-hook": {"yes"}},
				Body:    cassetter.Body{Type: cassetter.BodyTypeJSON, Content: map[string]any{"value": "hooked"}},
			},
			Response: cassetter.HTTPResponse{
				Status: http.StatusOK,
				Body:   cassetter.Body{Type: cassetter.BodyTypeText, Content: "replayed"},
			},
		}},
	}
	if err := cassette.Save(path); err != nil {
		t.Fatal(err)
	}
	base := roundTripFunc(func(*http.Request) (*http.Response, error) {
		return nil, errors.New("request reached the network")
	})
	transport := cassetter.NewTransport(
		base,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
		cassetter.WithMatchers(
			cassetter.MatcherMethod,
			cassetter.MatcherURI,
			cassetter.MatcherHeaders,
			cassetter.MatcherJSONBody,
		),
		cassetter.WithRequestHook(func(request *http.Request) error {
			request.URL.Path = "/hooked"
			request.Header.Set("X-Hook", "yes")
			request.Header.Set("Content-Type", "application/json")
			if err := request.Body.Close(); err != nil {
				return err
			}
			request.Body = io.NopCloser(strings.NewReader(`{"value":"hooked"}`))
			request.ContentLength = -1
			return nil
		}),
	)
	request, err := http.NewRequest(http.MethodPost, "https://example.com/original", strings.NewReader("original"))
	if err != nil {
		t.Fatal(err)
	}
	response, err := (&http.Client{Transport: transport}).Do(request)
	if err != nil {
		t.Fatal(err)
	}
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	if err := response.Body.Close(); err != nil {
		t.Fatal(err)
	}
	if string(body) != "replayed" {
		t.Fatalf("response body = %q", body)
	}
	if request.URL.Path != "/original" || request.Header.Get("X-Hook") != "" {
		t.Fatalf("original request was modified: %s %v", request.URL, request.Header)
	}
}

func TestRequestHookPreservesUnchangedGetBody(t *testing.T) {
	t.Parallel()
	base := roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if request.GetBody == nil {
			return nil, errors.New("GetBody was cleared")
		}
		return &http.Response{
			StatusCode: http.StatusNoContent,
			Header:     make(http.Header),
			Body:       http.NoBody,
			Request:    request,
		}, nil
	})
	transport := cassetter.NewTransport(
		base,
		cassetter.WithPath(filepath.Join(t.TempDir(), "cassette.yaml")),
		cassetter.WithRequestHook(func(request *http.Request) error {
			request.Header.Set("X-Hook", "yes")
			return nil
		}),
	)
	request, err := http.NewRequest(http.MethodPost, "https://example.com", strings.NewReader("body"))
	if err != nil {
		t.Fatal(err)
	}
	response, err := (&http.Client{Transport: transport}).Do(request)
	if err != nil {
		t.Fatal(err)
	}
	if err := response.Body.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestRequestHookSkipsCassette(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "missing.yaml")
	var calls atomic.Int64
	base := roundTripFunc(func(request *http.Request) (*http.Response, error) {
		calls.Add(1)
		return &http.Response{
			StatusCode: http.StatusNoContent,
			Header:     make(http.Header),
			Body:       http.NoBody,
			Request:    request,
		}, nil
	})
	transport := cassetter.NewTransport(
		base,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
		cassetter.WithRequestHook(func(*http.Request) error {
			return fmt.Errorf("wrapped: %w", cassetter.ErrSkipRecording)
		}),
	)
	response, err := (&http.Client{Transport: transport}).Get("https://example.com/live")
	if err != nil {
		t.Fatal(err)
	}
	if err := response.Body.Close(); err != nil {
		t.Fatal(err)
	}
	if calls.Load() != 1 {
		t.Fatalf("base transport calls = %d", calls.Load())
	}
	if _, err := os.Stat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("cassette exists after skipped request: %v", err)
	}
}

func TestTransportRejectsMissingRequestURL(t *testing.T) {
	t.Parallel()
	for name, hook := range map[string]cassetter.RequestHook{
		"missing initially": nil,
		"removed by hook": func(request *http.Request) error {
			request.URL = nil
			return nil
		},
	} {
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			body := &closeTrackingBody{Reader: strings.NewReader("content")}
			request := &http.Request{Method: http.MethodPost, Header: make(http.Header), Body: body}
			if hook != nil {
				request.URL = &url.URL{Scheme: "https", Host: "example.com"}
			}
			transport := cassetter.NewTransport(
				nil,
				cassetter.WithPath(filepath.Join(t.TempDir(), "cassette.yaml")),
				cassetter.WithRequestHook(hook),
			)
			if _, err := transport.RoundTrip(request); err == nil || !strings.Contains(err.Error(), "request URL") {
				t.Fatalf("request error = %v", err)
			}
			if !body.closed.Load() {
				t.Fatal("request body was not closed")
			}
		})
	}
}

func TestRequestHookFailureClosesRequestBody(t *testing.T) {
	t.Parallel()
	hookErr := errors.New("request hook failed")
	body := &closeTrackingBody{Reader: strings.NewReader("content")}
	request := &http.Request{
		Method: http.MethodPost,
		URL:    &url.URL{Scheme: "https", Host: "example.com"},
		Header: make(http.Header),
		Body:   body,
	}
	transport := cassetter.NewTransport(
		nil,
		cassetter.WithPath(filepath.Join(t.TempDir(), "cassette.yaml")),
		cassetter.WithRequestHook(func(*http.Request) error { return hookErr }),
	)
	if _, err := transport.RoundTrip(request); !errors.Is(err, hookErr) {
		t.Fatalf("request error = %v", err)
	}
	if !body.closed.Load() {
		t.Fatal("request body was not closed")
	}
}

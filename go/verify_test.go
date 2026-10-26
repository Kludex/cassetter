package cassetter_test

import (
	"bytes"
	"compress/gzip"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/Kludex/cassetter/go"
)

func TestVerifyComparesLiveResponseWithRecording(t *testing.T) {
	t.Parallel()
	cases := []struct {
		name     string
		recorded http.HandlerFunc
		live     http.HandlerFunc
		options  []cassetter.Option
		mismatch bool
	}{
		{
			name:     "same JSON",
			recorded: respond(200, "application/json", `{"a": 1, "b": [1, 2]}`),
			live:     respond(200, "application/json", `{"b":[1,2],"a":1}`),
		},
		{
			name:     "status",
			recorded: respond(200, "", ""),
			live:     respond(204, "", ""),
			mismatch: true,
		},
		{
			name:     "text body",
			recorded: respond(200, "text/plain", "hello"),
			live:     respond(200, "text/plain", "world"),
			mismatch: true,
		},
		{
			name:     "binary body",
			recorded: respond(200, "application/octet-stream", "\xff\x00"),
			live:     respond(200, "application/octet-stream", "\xff\x01"),
			mismatch: true,
		},
		{
			name:     "unlisted header",
			recorded: withHeader("X-Price", "1", respond(200, "text/plain", "ok")),
			live:     withHeader("X-Price", "2", respond(200, "text/plain", "ok")),
		},
		{
			name:     "listed header glob",
			recorded: withHeader("X-Price-Estimate", "1", respond(200, "text/plain", "ok")),
			live:     withHeader("X-Price-Estimate", "2", respond(200, "text/plain", "ok")),
			options:  []cassetter.Option{cassetter.WithCompare(cassetter.Compare{Headers: []string{"x-price-*"}})},
			mismatch: true,
		},
		{
			name:     "ignored JSON path",
			recorded: respond(200, "application/json", `{"id": "a", "items": [{"id": 1, "v": 2}]}`),
			live:     respond(200, "application/json", `{"id": "b", "items": [{"id": 9, "v": 2}]}`),
			options: []cassetter.Option{
				cassetter.WithCompare(cassetter.Compare{JSONIgnore: []string{"id", "items[0].id"}}),
			},
		},
		{
			name:     "compared JSON path",
			recorded: respond(200, "application/json", `{"id": "a", "v": 1}`),
			live:     respond(200, "application/json", `{"id": "a", "v": 2}`),
			options:  []cassetter.Option{cassetter.WithCompare(cassetter.Compare{JSONIgnore: []string{"id"}})},
			mismatch: true,
		},
		{
			name:     "float within tolerance",
			recorded: respond(200, "application/json", `{"v": [0.1, 2]}`),
			live:     respond(200, "application/json", `{"v": [0.1000001, 2.0]}`),
			options:  []cassetter.Option{cassetter.WithCompare(cassetter.Compare{FloatTolerance: 1e-6})},
		},
		{
			name:     "float outside tolerance",
			recorded: respond(200, "application/json", `{"v": 0.1}`),
			live:     respond(200, "application/json", `{"v": 0.2}`),
			options:  []cassetter.Option{cassetter.WithCompare(cassetter.Compare{FloatTolerance: 1e-6})},
			mismatch: true,
		},
		{
			name:     "SSE payloads",
			recorded: respond(200, "text/event-stream", "data: {\"id\": 1, \"t\": \"a\"}\n\ndata: [DONE]\n\n"),
			live:     respond(200, "text/event-stream", ": ping\r\n\r\ndata:{\"t\":\"a\",\"id\":2}\r\n\r\ndata: [DONE]\r\n\r\n"),
			options:  []cassetter.Option{cassetter.WithCompare(cassetter.Compare{SSE: true, JSONIgnore: []string{"id"}})},
		},
		{
			name:     "SSE payload differs",
			recorded: respond(200, "text/event-stream", "data: {\"t\": \"a\"}\n\n"),
			live:     respond(200, "text/event-stream", "data: {\"t\": \"b\"}\n\n"),
			options:  []cassetter.Option{cassetter.WithCompare(cassetter.Compare{SSE: true})},
			mismatch: true,
		},
		{
			name:     "status ignores tolerance",
			recorded: respond(200, "", ""),
			live:     respond(201, "", ""),
			options:  []cassetter.Option{cassetter.WithCompare(cassetter.Compare{FloatTolerance: 10})},
			mismatch: true,
		},
		{
			name:     "large integers",
			recorded: respond(200, "application/json", `{"id": 9007199254740992}`),
			live:     respond(200, "application/json", `{"id": 9007199254740993}`),
			mismatch: true,
		},
		{
			name:     "JSON string and number",
			recorded: respond(200, "application/json", `{"v": "1"}`),
			live:     respond(200, "application/json", `{"v": 1}`),
			mismatch: true,
		},
		{
			name:     "top-level JSON string and boolean",
			recorded: respond(200, "application/json", `"true"`),
			live:     respond(200, "application/json", `true`),
			mismatch: true,
		},
		{
			name:     "text trailing newline",
			recorded: respond(200, "text/plain", "a\n"),
			live:     respond(200, "text/plain", "a"),
			mismatch: true,
		},
		{
			name:     "body type",
			recorded: respond(200, "text/plain", "1"),
			live:     respond(200, "application/json", "1"),
			mismatch: true,
		},
		{
			name:     "ignored array element",
			recorded: respond(200, "application/json", `{"items": [{"id": 1}, 2]}`),
			live:     respond(200, "application/json", `{"items": [{"id": 9, "x": 1}, 2]}`),
			options:  []cassetter.Option{cassetter.WithCompare(cassetter.Compare{JSONIgnore: []string{"items[0]"}})},
		},
		{
			name:     "header casing variants merged",
			recorded: withHeader("X-Price", "1", respond(200, "text/plain", "ok")),
			live:     respond(200, "text/plain", "ok"),
			options: []cassetter.Option{
				cassetter.WithCompare(cassetter.Compare{Headers: []string{"x-price"}}),
				cassetter.WithBeforeCompareResponse(
					func(recorded, live cassetter.HTTPResponse) (cassetter.HTTPResponse, cassetter.HTTPResponse) {
						live.Headers = http.Header{"X-PRICE": {"1"}}
						return recorded, live
					},
				),
			},
		},
		{
			name:     "scrubbed and decompressed",
			recorded: respond(200, "application/json", `{"password": "a"}`),
			live:     gzipped(respond(200, "application/json", `{"password": "b"}`)),
		},
		{
			name:     "before compare hook",
			recorded: respond(200, "application/json", `{"v": 1}`),
			live:     respond(200, "application/json", `{"v": 1, "extra": null}`),
			options: []cassetter.Option{cassetter.WithBeforeCompareResponse(
				func(recorded, live cassetter.HTTPResponse) (cassetter.HTTPResponse, cassetter.HTTPResponse) {
					delete(live.Body.Content.(map[string]any), "extra")
					return recorded, live
				},
			)},
		},
		{
			name:     "response hook",
			recorded: respond(200, "text/plain", "ok"),
			live:     respond(500, "text/plain", "ok"),
			options: []cassetter.Option{cassetter.WithResponseHook(func(response *http.Response) error {
				response.StatusCode = 200
				return nil
			})},
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			t.Parallel()
			err := verifyAgainst(t, testCase.recorded, testCase.live, testCase.options...)
			var mismatch *cassetter.ResponseMismatchError
			if errors.As(err, &mismatch) != testCase.mismatch {
				t.Fatalf("mismatch = %v, want %v: %v", !testCase.mismatch, testCase.mismatch, err)
			}
			if !testCase.mismatch && err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestVerifyMismatchReportsUnifiedDiff(t *testing.T) {
	t.Parallel()
	err := verifyAgainst(
		t,
		withHeader("X-Price", "1", respond(200, "application/json", `{"content": "hi", "n": 1}`)),
		withHeader("X-Price", "2", respond(200, "application/json", `{"content": "hi", "n": 2}`)),
		cassetter.WithCompare(cassetter.Compare{Headers: []string{"x-price"}}),
	)
	var mismatch *cassetter.ResponseMismatchError
	if !errors.As(err, &mismatch) || !errors.Is(err, cassetter.ErrResponseMismatch) {
		t.Fatalf("err = %v", err)
	}
	lines := []string{
		"--- recorded", "+++ live", " status: 200", "-x-price: 1", "+x-price: 2", "-  \"n\": 1", "+  \"n\": 2",
	}
	for _, line := range lines {
		if !strings.Contains(mismatch.Diff, line+"\n") {
			t.Fatalf("diff does not contain %q:\n%s", line, mismatch.Diff)
		}
	}
	if mismatch.Method != http.MethodGet || !strings.HasSuffix(mismatch.URI, "/value") {
		t.Fatalf("mismatch = %#v", mismatch)
	}
}

func TestVerifyRejectsUnmatchedRequestsAndNeverWrites(t *testing.T) {
	t.Parallel()
	var calls atomic.Int64
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		calls.Add(1)
		_, _ = io.WriteString(writer, request.URL.Path)
	}))
	t.Cleanup(server.Close)
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	get(t, cassetter.NewTransport(nil, cassetter.WithPath(path)), server.URL+"/recorded")
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}

	transport := cassetter.NewTransport(
		nil,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeVerify),
	)
	client := &http.Client{Transport: transport}
	if _, err := client.Get(server.URL + "/other"); !errors.Is(err, cassetter.ErrNoMatch) {
		t.Fatalf("unmatched err = %v", err)
	}
	get(t, transport, server.URL+"/recorded")
	if err := transport.Close(); err != nil {
		t.Fatal(err)
	}
	after, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if calls.Load() != 2 || !bytes.Equal(before, after) {
		t.Fatalf("calls = %d, cassette changed = %v", calls.Load(), !bytes.Equal(before, after))
	}
}

func TestVerifyHookReceivesACopyOfTheRecording(t *testing.T) {
	t.Parallel()
	server := httptest.NewServer(respond(200, "application/json", `{"v": [1]}`))
	t.Cleanup(server.Close)
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	get(t, cassetter.NewTransport(nil, cassetter.WithPath(path)), server.URL)

	var seen []string
	transport := cassetter.NewTransport(
		nil,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeVerify),
		cassetter.WithBeforeCompareResponse(
			func(recorded, live cassetter.HTTPResponse) (cassetter.HTTPResponse, cassetter.HTTPResponse) {
				content := recorded.Body.Content.(map[string]any)
				seen = append(seen, fmt.Sprint(content["v"]))
				content["v"].([]any)[0] = "mutated"
				delete(content, "v")
				delete(live.Body.Content.(map[string]any), "v")
				return recorded, live
			},
		),
	)
	get(t, transport, server.URL)
	get(t, transport, server.URL)
	if err := transport.Close(); err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(seen, []string{"[1]", "[1]"}) {
		t.Fatalf("recorded bodies seen by the hook = %v", seen)
	}
}

func TestVerifyMismatchReportsScrubbedURI(t *testing.T) {
	t.Parallel()
	var status atomic.Int64
	status.Store(200)
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		writer.WriteHeader(int(status.Load()))
	}))
	t.Cleanup(server.Close)
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	url := server.URL + "/value?api_key=secret"
	get(t, cassetter.NewTransport(nil, cassetter.WithPath(path)), url)

	status.Store(500)
	transport := cassetter.NewTransport(
		nil,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeVerify),
	)
	_, err := (&http.Client{Transport: transport}).Get(url)
	var mismatch *cassetter.ResponseMismatchError
	if !errors.As(err, &mismatch) {
		t.Fatalf("err = %v", err)
	}
	if strings.Contains(mismatch.Error(), "secret") || !strings.Contains(mismatch.URI, "api_key=") {
		t.Fatalf("err = %v", err)
	}
}

// verifyAgainst records recorded, then verifies live against it and returns every error the verify run reported.
func verifyAgainst(t *testing.T, recorded http.Handler, live http.Handler, options ...cassetter.Option) error {
	t.Helper()
	var handler atomic.Pointer[http.Handler]
	handler.Store(&recorded)
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		(*handler.Load()).ServeHTTP(writer, request)
	}))
	t.Cleanup(server.Close)
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	get(t, cassetter.NewTransport(nil, cassetter.WithPath(path)), server.URL+"/value")

	handler.Store(&live)
	options = append(options, cassetter.WithPath(path), cassetter.WithRecordMode(cassetter.RecordModeVerify))
	transport := cassetter.NewTransport(nil, options...)
	response, err := (&http.Client{Transport: transport}).Get(server.URL + "/value")
	if err == nil {
		_, readErr := io.ReadAll(response.Body)
		err = errors.Join(readErr, response.Body.Close())
	}
	return errors.Join(err, transport.Close())
}

func get(t *testing.T, transport *cassetter.Transport, url string) {
	t.Helper()
	response, err := (&http.Client{Transport: transport}).Get(url)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := io.ReadAll(response.Body); err != nil {
		t.Fatal(err)
	}
	if err := response.Body.Close(); err != nil {
		t.Fatal(err)
	}
}

func respond(status int, contentType string, body string) http.HandlerFunc {
	return func(writer http.ResponseWriter, _ *http.Request) {
		if contentType != "" {
			writer.Header().Set("Content-Type", contentType)
		}
		writer.WriteHeader(status)
		_, _ = io.WriteString(writer, body)
	}
}

func withHeader(name string, value string, next http.HandlerFunc) http.HandlerFunc {
	return func(writer http.ResponseWriter, request *http.Request) {
		writer.Header().Set(name, value)
		next(writer, request)
	}
}

func gzipped(next http.HandlerFunc) http.HandlerFunc {
	return func(writer http.ResponseWriter, request *http.Request) {
		recorder := httptest.NewRecorder()
		next(recorder, request)
		var buffer bytes.Buffer
		compressor := gzip.NewWriter(&buffer)
		_, _ = compressor.Write(recorder.Body.Bytes())
		_ = compressor.Close()
		writer.Header().Set("Content-Type", recorder.Header().Get("Content-Type"))
		writer.Header().Set("Content-Encoding", "gzip")
		writer.WriteHeader(recorder.Code)
		_, _ = writer.Write(buffer.Bytes())
	}
}

package cassetter_test

import (
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/Kludex/cassetter/go"
)

func TestTransportReportsConfigurationAndReplayErrors(t *testing.T) {
	t.Parallel()
	tests := map[string]*cassetter.Transport{
		"missing path": cassetter.NewTransport(nil),
		"unknown mode": cassetter.NewTransport(
			nil,
			cassetter.WithPath(filepath.Join(t.TempDir(), "unknown.yaml")),
			cassetter.WithRecordMode(cassetter.RecordMode("unknown")),
		),
	}
	for name, transport := range tests {
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			client := &http.Client{Transport: transport}
			if _, err := client.Get("https://example.invalid"); err == nil {
				t.Fatal("request succeeded")
			}
		})
	}

	client := &http.Client{Transport: cassetter.NewTransport(
		nil,
		cassetter.WithPath(filepath.Join(t.TempDir(), "missing.yaml")),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
	)}
	_, err := client.Get("https://example.invalid/missing")
	if !errors.Is(err, cassetter.ErrNoMatch) {
		t.Fatalf("replay error = %v", err)
	}
	var noMatch *cassetter.NoMatchError
	if !errors.As(err, &noMatch) || noMatch.Method != http.MethodGet || noMatch.URI == "" {
		t.Fatalf("replay error = %#v", err)
	}
	if !strings.Contains(err.Error(), "GET https://example.invalid/missing") {
		t.Fatalf("replay error = %q", err)
	}
}

func TestTransportStreamsRecordsAndReplays(t *testing.T) {
	firstWritten := make(chan struct{})
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		writer.Header().Set("Content-Type", "text/event-stream")
		writer.Header().Set("X-Request-ID", "abc")
		writer.WriteHeader(http.StatusOK)
		_, _ = writer.Write([]byte("first\n"))
		writer.(http.Flusher).Flush()
		close(firstWritten)
		<-release
		_, _ = writer.Write([]byte("data: {\"access_token\":\"secret\"}\n\n"))
	}))

	path := filepath.Join(t.TempDir(), "stream.yaml")
	client := &http.Client{Transport: cassetter.NewTransport(
		http.DefaultTransport,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeOnce),
	)}
	request, err := http.NewRequest(http.MethodGet, server.URL+"/events?api_key=secret", nil)
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Authorization", "Bearer secret")
	response, err := client.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	<-firstWritten
	first := make([]byte, len("first\n"))
	if _, err := io.ReadFull(response.Body, first); err != nil {
		t.Fatal(err)
	}
	if string(first) != "first\n" {
		t.Fatalf("first chunk = %q", first)
	}
	if _, err := os.Stat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("cassette was saved before the stream completed: %v", err)
	}
	close(release)
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	if err := response.Body.Close(); err != nil {
		t.Fatal(err)
	}
	server.Close()

	if string(body) != "data: {\"access_token\":\"secret\"}\n\n" {
		t.Fatalf("remaining body = %q", body)
	}
	recorded, err := cassetter.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	interaction := recorded.Interactions[0]
	if interaction.Request.URI != server.URL+"/events?api_key=[FILTERED]" {
		t.Fatalf("recorded URI = %q", interaction.Request.URI)
	}
	if interaction.Request.Headers.Get("authorization") != "" {
		t.Fatal("authorization was written to disk")
	}
	if strings.Contains(interaction.Response.Body.Content.(string), "secret") {
		t.Fatal("response secret was written to disk")
	}

	replayClient := &http.Client{Transport: cassetter.NewTransport(
		http.DefaultTransport,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
	)}
	replayed, err := replayClient.Get(server.URL + "/events?api_key=different")
	if err != nil {
		t.Fatal(err)
	}
	replayedBody, err := io.ReadAll(replayed.Body)
	if err != nil {
		t.Fatal(err)
	}
	if err := replayed.Body.Close(); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(replayedBody), "secret") || !strings.Contains(string(replayedBody), "[FILTERED]") {
		t.Fatalf("replayed body = %q", replayedBody)
	}
	_, err = replayClient.Get(server.URL + "/events?api_key=third")
	if !errors.Is(err, cassetter.ErrNoMatch) {
		t.Fatalf("second replay error = %v", err)
	}
}

func TestTransportStreamsRequestBodies(t *testing.T) {
	t.Parallel()
	firstRead := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		first := make([]byte, 5)
		if _, err := io.ReadFull(request.Body, first); err != nil {
			t.Errorf("read first request chunk: %v", err)
			return
		}
		close(firstRead)
		rest, err := io.ReadAll(request.Body)
		if err != nil {
			t.Errorf("read remaining request body: %v", err)
			return
		}
		if string(first)+string(rest) != "first-second" {
			t.Errorf("request body = %q", string(first)+string(rest))
		}
		writer.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	path := filepath.Join(t.TempDir(), "request-stream.yaml")
	client := &http.Client{Transport: cassetter.NewTransport(nil, cassetter.WithPath(path))}
	reader, writer := io.Pipe()
	result := make(chan error, 1)
	go func() {
		request, err := http.NewRequest(http.MethodPost, server.URL, reader)
		if err != nil {
			result <- err
			return
		}
		request.Header.Set("Content-Type", "text/plain")
		response, err := client.Do(request)
		if err == nil {
			err = response.Body.Close()
		}
		result <- err
	}()
	if _, err := io.WriteString(writer, "first"); err != nil {
		t.Fatal(err)
	}
	select {
	case <-firstRead:
	case <-time.After(time.Second):
		t.Fatal("the transport buffered the request instead of streaming it")
	}
	if _, err := io.WriteString(writer, "-second"); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	if err := <-result; err != nil {
		t.Fatal(err)
	}
	cassette, err := cassetter.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if content := cassette.Interactions[0].Request.Body.Content; content != "first-second" {
		t.Fatalf("recorded request body = %q", content)
	}
}

func TestTransportPlaybackIsRaceSafe(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "race.yaml")
	uri := "https://example.invalid/value"
	cassette := &cassetter.Cassette{Version: 1}
	for _, value := range []string{"one", "two"} {
		cassette.Interactions = append(cassette.Interactions, cassetter.HTTPInteraction{
			Request: cassetter.HTTPRequest{Method: http.MethodGet, URI: uri},
			Response: cassetter.HTTPResponse{
				Status: http.StatusOK,
				Body:   cassetter.Body{Type: cassetter.BodyTypeText, Content: value},
			},
		})
	}
	if err := cassette.Save(path); err != nil {
		t.Fatal(err)
	}
	client := &http.Client{Transport: cassetter.NewTransport(
		nil,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
	)}
	var wait sync.WaitGroup
	results := make(chan string, 2)
	for range 2 {
		wait.Add(1)
		go func() {
			defer wait.Done()
			response, err := client.Get(uri)
			if err != nil {
				results <- "error: " + err.Error()
				return
			}
			defer func() {
				if err := response.Body.Close(); err != nil {
					t.Errorf("close response: %v", err)
				}
			}()
			body, err := io.ReadAll(response.Body)
			if err != nil {
				results <- "error: " + err.Error()
				return
			}
			results <- string(body)
		}()
	}
	wait.Wait()
	close(results)
	got := make([]string, 0, 2)
	for result := range results {
		got = append(got, result)
	}
	sort.Strings(got)
	if strings.Join(got, ",") != "one,two" {
		t.Fatalf("responses = %v", got)
	}
}

func TestTransportClosesIdleConnections(t *testing.T) {
	t.Parallel()
	base := &idleClosingTransport{}
	transport := cassetter.NewTransport(base, cassetter.WithPath(filepath.Join(t.TempDir(), "unused.yaml")))
	transport.CloseIdleConnections()
	if !base.closed {
		t.Fatal("CloseIdleConnections was not forwarded")
	}
}

type idleClosingTransport struct {
	closed bool
}

func (transport *idleClosingTransport) RoundTrip(*http.Request) (*http.Response, error) {
	return nil, errors.New("not implemented")
}

func (transport *idleClosingTransport) CloseIdleConnections() {
	transport.closed = true
}

func TestTransportCloseStopsAnUnboundedResponse(t *testing.T) {
	started := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		writer.Header().Set("Content-Type", "text/plain")
		_, _ = io.WriteString(writer, "first")
		writer.(http.Flusher).Flush()
		close(started)
		<-request.Context().Done()
	}))
	defer server.Close()
	path := filepath.Join(t.TempDir(), "close.yaml")
	client := &http.Client{Transport: cassetter.NewTransport(nil, cassetter.WithPath(path))}
	response, err := client.Get(server.URL)
	if err != nil {
		t.Fatal(err)
	}
	<-started
	first := make([]byte, len("first"))
	if _, err := io.ReadFull(response.Body, first); err != nil {
		t.Fatal(err)
	}
	closed := make(chan error, 1)
	go func() {
		closed <- response.Body.Close()
	}()
	select {
	case err := <-closed:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("Close blocked while draining an unbounded response")
	}
	if _, err := cassetter.Load(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("incomplete response was recorded: %v", err)
	}
}

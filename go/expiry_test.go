package cassetter_test

import (
	"bytes"
	"errors"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/Kludex/cassetter/go"
)

func TestTransportRejectsExpiredCassette(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "expired.yaml")
	cassette := &cassetter.Cassette{
		Version: 1,
		Interactions: []cassetter.HTTPInteraction{{
			Request:    cassetter.HTTPRequest{Method: http.MethodGet, URI: "https://example.com"},
			Response:   cassetter.HTTPResponse{Status: http.StatusOK},
			RecordedAt: time.Now().Add(-48 * time.Hour).UTC().Format(time.RFC3339Nano),
		}},
	}
	if err := cassette.Save(path); err != nil {
		t.Fatal(err)
	}
	transport := cassetter.NewTransport(
		nil,
		cassetter.WithPath(path),
		cassetter.WithMaxAge(time.Hour),
		cassetter.WithExpiryAction(cassetter.ExpiryFail),
	)
	err := transport.Initialize()
	if !errors.Is(err, cassetter.ErrCassetteExpired) {
		t.Fatalf("initialization error = %v", err)
	}
	var expired *cassetter.CassetteExpiredError
	if !errors.As(err, &expired) || expired.Path != path || expired.Age < 47*time.Hour || expired.MaxAge != time.Hour {
		t.Fatalf("expiry error = %#v", expired)
	}
}

func TestTransportUsesNewestProtocolTimestampForExpiry(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "current.yaml")
	old := time.Now().Add(-48 * time.Hour).UTC().Format(time.RFC3339Nano)
	current := time.Now().UTC().Format(time.RFC3339Nano)
	cassette := &cassetter.Cassette{
		Version:               1,
		Interactions:          []cassetter.HTTPInteraction{{RecordedAt: old}},
		GRPCInteractions:      []cassetter.GRPCInteraction{{RecordedAt: current}},
		WebSocketInteractions: []cassetter.WebSocketInteraction{{RecordedAt: old}},
	}
	cassette.Interactions[0].Request = cassetter.HTTPRequest{Method: http.MethodGet, URI: "https://example.com"}
	cassette.Interactions[0].Response.Status = http.StatusOK
	cassette.GRPCInteractions[0].Request.Method = "/example.Service/Get"
	cassette.WebSocketInteractions[0].URI = "wss://example.com"
	if err := cassette.Save(path); err != nil {
		t.Fatal(err)
	}
	transport := cassetter.NewTransport(
		nil,
		cassetter.WithPath(path),
		cassetter.WithMaxAge(time.Hour),
		cassetter.WithExpiryAction(cassetter.ExpiryFail),
	)
	if err := transport.Initialize(); err != nil {
		t.Fatal(err)
	}
}

func TestTransportRerecordsExpiredCassette(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "expired.yaml")
	cassette := &cassetter.Cassette{
		Version: 1,
		Interactions: []cassetter.HTTPInteraction{{
			Request:    cassetter.HTTPRequest{Method: http.MethodGet, URI: "https://old.example.com"},
			Response:   cassetter.HTTPResponse{Status: http.StatusOK},
			RecordedAt: time.Now().Add(-48 * time.Hour).UTC().Format(time.RFC3339Nano),
		}},
	}
	if err := cassette.Save(path); err != nil {
		t.Fatal(err)
	}
	transport := cassetter.NewTransport(
		responseTransport("new", 3),
		cassetter.WithPath(path),
		cassetter.WithMaxAge(time.Hour),
		cassetter.WithExpiryAction(cassetter.ExpiryRerecord),
	)
	if err := transport.Initialize(); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("expired cassette still exists: %v", err)
	}
	response, err := (&http.Client{Transport: transport}).Get("https://new.example.com")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := io.Copy(io.Discard, response.Body); err != nil {
		t.Fatal(err)
	}
	if err := response.Body.Close(); err != nil {
		t.Fatal(err)
	}
	recorded, err := cassetter.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(recorded.Interactions) != 1 || recorded.Interactions[0].Request.URI != "https://new.example.com" {
		t.Fatalf("interactions = %#v", recorded.Interactions)
	}
}

func TestTransportWarnsForExpiredCassette(t *testing.T) {
	path := filepath.Join(t.TempDir(), "expired.yaml")
	cassette := &cassetter.Cassette{
		Version: 1,
		Interactions: []cassetter.HTTPInteraction{{
			Request:    cassetter.HTTPRequest{Method: http.MethodGet, URI: "https://example.com"},
			Response:   cassetter.HTTPResponse{Status: http.StatusOK},
			RecordedAt: time.Now().Add(-48 * time.Hour).UTC().Format(time.RFC3339Nano),
		}},
	}
	if err := cassette.Save(path); err != nil {
		t.Fatal(err)
	}
	var output bytes.Buffer
	writer, flags, prefix := log.Writer(), log.Flags(), log.Prefix()
	log.SetOutput(&output)
	log.SetFlags(0)
	log.SetPrefix("")
	t.Cleanup(func() {
		log.SetOutput(writer)
		log.SetFlags(flags)
		log.SetPrefix(prefix)
	})
	transport := cassetter.NewTransport(nil, cassetter.WithPath(path), cassetter.WithMaxAge(time.Hour))
	if err := transport.Initialize(); err != nil {
		t.Fatal(err)
	}
	if warning := output.String(); !strings.Contains(warning, "cassetter warning: cassette expired") {
		t.Fatalf("warning = %q", warning)
	}
}

func TestTransportValidatesExpiryTimestamps(t *testing.T) {
	t.Parallel()
	for name, interactions := range map[string][]cassetter.HTTPInteraction{
		"empty cassette": nil,
		"empty timestamp": {{
			Request:  cassetter.HTTPRequest{Method: http.MethodGet, URI: "https://example.com"},
			Response: cassetter.HTTPResponse{Status: http.StatusOK},
		}},
		"invalid timestamp": {{
			Request:    cassetter.HTTPRequest{Method: http.MethodGet, URI: "https://example.com"},
			Response:   cassetter.HTTPResponse{Status: http.StatusOK},
			RecordedAt: "not-a-timestamp",
		}},
	} {
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			path := filepath.Join(t.TempDir(), "cassette.yaml")
			if err := (&cassetter.Cassette{Version: 1, Interactions: interactions}).Save(path); err != nil {
				t.Fatal(err)
			}
			transport := cassetter.NewTransport(nil, cassetter.WithPath(path), cassetter.WithMaxAge(time.Hour))
			err := transport.Initialize()
			if name == "invalid timestamp" {
				if err == nil || !strings.Contains(err.Error(), "parse recorded_at") {
					t.Fatalf("initialization error = %v", err)
				}
			} else if err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestTransportRejectsInvalidExpiryConfiguration(t *testing.T) {
	t.Parallel()
	tests := map[string]*cassetter.Transport{
		"negative age": cassetter.NewTransport(
			nil,
			cassetter.WithPath(filepath.Join(t.TempDir(), "negative.yaml")),
			cassetter.WithMaxAge(-time.Second),
		),
		"unknown action": cassetter.NewTransport(
			nil,
			cassetter.WithPath(filepath.Join(t.TempDir(), "action.yaml")),
			cassetter.WithExpiryAction(cassetter.ExpiryAction("unknown")),
		),
	}
	for name, transport := range tests {
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			if err := transport.Initialize(); err == nil {
				t.Fatal("Initialize accepted invalid expiry configuration")
			}
		})
	}
}

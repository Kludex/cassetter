package cassetter_test

import (
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Kludex/cassetter/go"
)

func TestExpiredReplayOnlyCassetteCannotRecord(t *testing.T) {
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
	var calls atomic.Int64
	transport := cassetter.NewTransport(
		roundTripFunc(func(*http.Request) (*http.Response, error) {
			calls.Add(1)
			return nil, errors.New("request reached the network")
		}),
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
		cassetter.WithMaxAge(time.Hour),
		cassetter.WithExpiryAction(cassetter.ExpiryRerecord),
	)
	if err := transport.Initialize(); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("expired cassette still exists: %v", err)
	}
	request, err := http.NewRequest(http.MethodGet, "https://new.example.com", nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := transport.RoundTrip(request); !errors.Is(err, cassetter.ErrNoMatch) {
		t.Fatalf("request error = %v", err)
	}
	if calls.Load() != 0 {
		t.Fatalf("base transport calls = %d", calls.Load())
	}
}

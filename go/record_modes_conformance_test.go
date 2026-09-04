package cassetter_test

import (
	"bytes"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"testing"

	"github.com/Kludex/cassetter/go"
)

type storedInteraction struct {
	URI    string `json:"uri"`
	Status int    `json:"status"`
}

type recordModeCase struct {
	Name              string               `json:"name"`
	Mode              cassetter.RecordMode `json:"mode"`
	Existing          bool                 `json:"existing"`
	Requests          []string             `json:"requests"`
	ExpectedOutcomes  []string             `json:"expectedOutcomes"`
	ExpectedBaseCalls int                  `json:"expectedBaseCalls"`
	ExpectedFile      *[]storedInteraction `json:"expectedFile"`
}

func TestRecordModeConformance(t *testing.T) {
	t.Parallel()
	fixtures := filepath.Join(conformanceFixtures(t), "record-modes")
	cases := loadJSONFixture[[]recordModeCase](t, filepath.Join(fixtures, "cases.json"))
	for _, testCase := range cases {
		t.Run(testCase.Name, func(t *testing.T) {
			t.Parallel()
			path := filepath.Join(t.TempDir(), "cassette.yaml")
			if testCase.Existing {
				content, err := os.ReadFile(filepath.Join(fixtures, "existing.yaml"))
				if err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(path, content, 0o600); err != nil {
					t.Fatal(err)
				}
			}
			baseCalls := 0
			base := roundTripFunc(func(request *http.Request) (*http.Response, error) {
				baseCalls++
				content := []byte(`{"source":"live"}`)
				return &http.Response{
					StatusCode:    299,
					Header:        http.Header{"content-type": []string{"application/json"}},
					Body:          io.NopCloser(bytes.NewReader(content)),
					ContentLength: int64(len(content)),
					Request:       request,
				}, nil
			})
			transport := cassetter.NewTransport(
				base,
				cassetter.WithPath(path),
				cassetter.WithRecordMode(testCase.Mode),
			)
			if err := transport.Initialize(); err != nil {
				t.Fatal(err)
			}
			client := &http.Client{Transport: transport}
			outcomes := make([]string, 0, len(testCase.Requests))
			for _, uri := range testCase.Requests {
				callsBefore := baseCalls
				response, err := client.Get(uri)
				if errors.Is(err, cassetter.ErrNoMatch) {
					outcomes = append(outcomes, "no_match")
					continue
				}
				if err != nil {
					t.Fatal(err)
				}
				if baseCalls == callsBefore {
					outcomes = append(outcomes, "replay")
				} else {
					outcomes = append(outcomes, "live")
				}
				if _, err := io.Copy(io.Discard, response.Body); err != nil {
					t.Fatal(err)
				}
				if err := response.Body.Close(); err != nil {
					t.Fatal(err)
				}
			}
			if err := transport.Close(); err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(outcomes, testCase.ExpectedOutcomes) {
				t.Fatalf("outcomes = %v, want %v", outcomes, testCase.ExpectedOutcomes)
			}
			if baseCalls != testCase.ExpectedBaseCalls {
				t.Fatalf("base calls = %d, want %d", baseCalls, testCase.ExpectedBaseCalls)
			}
			assertStoredInteractions(t, path, testCase.ExpectedFile)
		})
	}
}

func assertStoredInteractions(t *testing.T, path string, expected *[]storedInteraction) {
	t.Helper()
	if expected == nil {
		if _, err := os.Stat(path); !errors.Is(err, os.ErrNotExist) {
			t.Fatalf("cassette exists or returned unexpected error: %v", err)
		}
		return
	}
	cassette, err := cassetter.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	actual := make([]storedInteraction, 0, len(cassette.Interactions))
	for _, interaction := range cassette.Interactions {
		actual = append(actual, storedInteraction{
			URI:    interaction.Request.URI,
			Status: interaction.Response.Status,
		})
	}
	sort.Slice(actual, func(left int, right int) bool {
		return actual[left].URI < actual[right].URI
	})
	if !reflect.DeepEqual(actual, *expected) {
		t.Fatalf("stored interactions = %v, want %v", actual, *expected)
	}
}

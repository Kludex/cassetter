package cassetter_test

import (
	"bytes"
	"errors"
	"io"
	"net/http"
	"path/filepath"
	"testing"

	"github.com/Kludex/cassetter/go"
)

type matchingRequest struct {
	Method  string         `json:"method"`
	URI     string         `json:"uri"`
	Headers http.Header    `json:"headers"`
	Body    cassetter.Body `json:"body"`
}

type matchingCase struct {
	Name             string              `json:"name"`
	MatchOn          []cassetter.Matcher `json:"matchOn"`
	IgnoreJSONPaths  []string            `json:"ignoreJsonPaths"`
	Requests         []matchingRequest   `json:"requests"`
	ExpectedStatuses []*int              `json:"expectedStatuses"`
}

func TestMatchingConformance(t *testing.T) {
	t.Parallel()
	fixtures := filepath.Join(conformanceFixtures(t), "matching")
	cases := loadJSONFixture[[]matchingCase](t, filepath.Join(fixtures, "cases.json"))
	for _, testCase := range cases {
		t.Run(testCase.Name, func(t *testing.T) {
			t.Parallel()
			options := []cassetter.Option{
				cassetter.WithPath(filepath.Join(fixtures, "cassette.yaml")),
				cassetter.WithRecordMode(cassetter.RecordModeNone),
			}
			if testCase.MatchOn != nil {
				options = append(options, cassetter.WithMatchers(testCase.MatchOn...))
			}
			if testCase.IgnoreJSONPaths != nil {
				options = append(options, cassetter.WithIgnoredJSONPaths(testCase.IgnoreJSONPaths...))
			}
			transport := cassetter.NewTransport(nil, options...)
			client := &http.Client{Transport: transport}
			for index, value := range testCase.Requests {
				content, err := conformanceBodyBytes(value.Body)
				if err != nil {
					t.Fatal(err)
				}
				request, err := http.NewRequest(value.Method, value.URI, bytes.NewReader(content))
				if err != nil {
					t.Fatal(err)
				}
				request.Header = value.Headers.Clone()
				response, err := client.Do(request)
				expected := testCase.ExpectedStatuses[index]
				if expected == nil {
					if !errors.Is(err, cassetter.ErrNoMatch) {
						t.Fatalf("request %d error = %v, want ErrNoMatch", index, err)
					}
					continue
				}
				if err != nil {
					t.Fatal(err)
				}
				if response.StatusCode != *expected {
					t.Fatalf("request %d status = %d, want %d", index, response.StatusCode, *expected)
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
		})
	}
}

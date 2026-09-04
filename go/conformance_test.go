package cassetter_test

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"github.com/Kludex/cassetter/go"
)

type formatCase struct {
	Name     string `json:"name"`
	Cassette string `json:"cassette"`
	Expected string `json:"expected"`
}

func TestFormatConformance(t *testing.T) {
	t.Parallel()
	fixtures := filepath.Join("..", "conformance", "format")
	for _, testCase := range loadFormatCases(t, fixtures) {
		t.Run(testCase.Name, func(t *testing.T) {
			t.Parallel()
			cassette, err := cassetter.Load(filepath.Join(fixtures, testCase.Cassette))
			if err != nil {
				t.Fatal(err)
			}
			assertCanonicalJSON(t, canonicalCassette(cassette), filepath.Join(fixtures, testCase.Expected))

			output := filepath.Join(t.TempDir(), testCase.Cassette)
			if err := cassette.Save(output); err != nil {
				t.Fatal(err)
			}
			reloaded, err := cassetter.Load(output)
			if err != nil {
				t.Fatal(err)
			}
			assertCanonicalJSON(t, canonicalCassette(reloaded), filepath.Join(fixtures, testCase.Expected))
		})
	}
}

func loadFormatCases(t *testing.T, fixtures string) []formatCase {
	t.Helper()
	content, err := os.ReadFile(filepath.Join(fixtures, "cases.json"))
	if err != nil {
		t.Fatal(err)
	}
	var cases []formatCase
	if err := json.Unmarshal(content, &cases); err != nil {
		t.Fatal(err)
	}
	return cases
}

func assertCanonicalJSON(t *testing.T, actual any, expectedPath string) {
	t.Helper()
	expectedContent, err := os.ReadFile(expectedPath)
	if err != nil {
		t.Fatal(err)
	}
	var expected any
	if err := json.Unmarshal(expectedContent, &expected); err != nil {
		t.Fatal(err)
	}
	actualContent, err := json.Marshal(actual)
	if err != nil {
		t.Fatal(err)
	}
	var normalizedActual any
	if err := json.Unmarshal(actualContent, &normalizedActual); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(normalizedActual, expected) {
		actualIndented, _ := json.MarshalIndent(normalizedActual, "", "  ")
		t.Fatalf("canonical cassette does not match %s:\n%s", expectedPath, actualIndented)
	}
}

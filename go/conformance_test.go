package cassetter_test

import (
	"bytes"
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
	fixtures := formatFixtures(t)
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

func TestPackagedFormatFixturesMatchShared(t *testing.T) {
	t.Parallel()
	shared := filepath.Join("..", "conformance", "format")
	if _, err := os.Stat(shared); err != nil {
		t.Skip("shared fixtures are outside the published Go module")
	}
	packaged := filepath.Join("testdata", "conformance", "format")
	files := []string{"cases.json"}
	for _, testCase := range loadFormatCases(t, shared) {
		files = append(files, testCase.Cassette, testCase.Expected)
	}
	for _, name := range files {
		sharedContent, err := os.ReadFile(filepath.Join(shared, name))
		if err != nil {
			t.Fatal(err)
		}
		packagedContent, err := os.ReadFile(filepath.Join(packaged, name))
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(packagedContent, sharedContent) {
			t.Fatalf("packaged conformance fixture %s is stale", name)
		}
	}
}

func formatFixtures(t *testing.T) string {
	t.Helper()
	shared := filepath.Join("..", "conformance", "format")
	if _, err := os.Stat(shared); err == nil {
		return shared
	}
	return filepath.Join("testdata", "conformance", "format")
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

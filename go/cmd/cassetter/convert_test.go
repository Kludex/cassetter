package main_test

import (
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Kludex/cassetter/go"
)

func TestCLIConvertsYAMLAndTOML(t *testing.T) {
	t.Parallel()
	directory := t.TempDir()
	yamlPath := filepath.Join(directory, "input.yaml")
	tomlPath := filepath.Join(directory, "output.toml")
	roundTripPath := filepath.Join(directory, "roundtrip.yaml")
	if err := os.WriteFile(yamlPath, []byte(secretVCRCassette), 0o600); err != nil {
		t.Fatal(err)
	}
	output := runCLI(t, "convert", yamlPath, tomlPath)
	if !strings.Contains(output, "Converted 1 interaction(s)") {
		t.Fatalf("convert output = %q", output)
	}
	converted, err := cassetter.Load(tomlPath)
	if err != nil {
		t.Fatal(err)
	}
	interaction := converted.Interactions[0]
	if len(headerValues(interaction.Request.Headers, "authorization")) != 0 ||
		strings.Contains(interaction.Request.URI, "secret") {
		t.Fatalf("converted request = %#v", interaction.Request)
	}
	if interaction.Response.Body.Content.(map[string]any)["access_token"] != "[FILTERED]" {
		t.Fatalf("converted response body = %#v", interaction.Response.Body)
	}
	inspect := runCLI(t, "inspect", tomlPath)
	if !strings.Contains(inspect, "HTTP interactions: 1") {
		t.Fatalf("inspect output = %q", inspect)
	}
	runCLI(t, "convert", tomlPath, roundTripPath)
	if difference := runCLI(t, "diff", tomlPath, roundTripPath); difference != "No differences.\n" {
		t.Fatalf("cross-format diff = %q", difference)
	}
}

func TestCLIConvertCanSkipScrubbing(t *testing.T) {
	t.Parallel()
	directory := t.TempDir()
	input := filepath.Join(directory, "input.yaml")
	output := filepath.Join(directory, "output.toml")
	if err := os.WriteFile(input, []byte(secretVCRCassette), 0o600); err != nil {
		t.Fatal(err)
	}
	runCLI(t, "convert", "--no-scrub", input, output)
	converted, err := cassetter.Load(output)
	if err != nil {
		t.Fatal(err)
	}
	interaction := converted.Interactions[0]
	if strings.Join(headerValues(interaction.Request.Headers, "authorization"), ",") != "Bearer secret" ||
		!strings.Contains(interaction.Request.URI, "api_key=secret") {
		t.Fatalf("converted request = %#v", interaction.Request)
	}
	runCLI(t, "scrub", output)
	scrubbed, err := cassetter.Load(output)
	if err != nil {
		t.Fatal(err)
	}
	if len(headerValues(scrubbed.Interactions[0].Request.Headers, "authorization")) != 0 {
		t.Fatalf("scrubbed TOML request = %#v", scrubbed.Interactions[0].Request)
	}
}

func TestCLIConvertRequiresForceToOverwrite(t *testing.T) {
	t.Parallel()
	directory := t.TempDir()
	input := filepath.Join(directory, "input.yaml")
	output := filepath.Join(directory, "output.toml")
	if err := os.WriteFile(input, []byte(secretVCRCassette), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(output, []byte("existing"), 0o600); err != nil {
		t.Fatal(err)
	}
	failure := runCLIStatus(t, 1, "convert", input, output)
	if !strings.Contains(failure, "use --force to overwrite") {
		t.Fatalf("convert output = %q", failure)
	}
	runCLI(t, "convert", input, output, "--force")
	if _, err := cassetter.Load(output); err != nil {
		t.Fatal(err)
	}
}

func TestCLIConvertsDirectoriesAndContinuesAfterErrors(t *testing.T) {
	t.Parallel()
	directory := t.TempDir()
	nested := filepath.Join(directory, "nested")
	if err := os.Mkdir(nested, 0o755); err != nil {
		t.Fatal(err)
	}
	good := filepath.Join(nested, "good.yaml")
	bad := filepath.Join(directory, "bad.yaml")
	if err := os.WriteFile(good, []byte(secretVCRCassette), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(bad, []byte("not: [valid"), 0o600); err != nil {
		t.Fatal(err)
	}
	output := runCLIStatus(t, 1, "convert", directory, "out.toml")
	if !strings.Contains(output, "Converted 1 file(s), failed 1") {
		t.Fatalf("convert output = %q", output)
	}
	if _, err := cassetter.Load(filepath.Join(nested, "good.toml")); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(directory, "bad.toml")); !os.IsNotExist(err) {
		t.Fatalf("bad output exists: %v", err)
	}
}

func TestCLIConvertsDirectoryIntoOutputDirectory(t *testing.T) {
	t.Parallel()
	root := t.TempDir()
	input := filepath.Join(root, "input")
	output := filepath.Join(root, "output")
	nested := filepath.Join(input, "nested")
	if err := os.MkdirAll(nested, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(nested, "cassette.yaml"), []byte(secretVCRCassette), 0o600); err != nil {
		t.Fatal(err)
	}
	runCLI(t, "convert", input, output, "--to", "toml")
	if _, err := cassetter.Load(filepath.Join(output, "nested", "cassette.toml")); err != nil {
		t.Fatal(err)
	}
}

func TestCLIConvertsVCRInPlace(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	if err := os.WriteFile(path, []byte(secretVCRCassette), 0o600); err != nil {
		t.Fatal(err)
	}
	failure := runCLIStatus(t, 1, "convert", path, path)
	if !strings.Contains(failure, "in place requires --force") {
		t.Fatalf("convert output = %q", failure)
	}
	runCLI(t, "convert", path, path, "--force")
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(content), "string:") || !strings.Contains(string(content), "type: json") {
		t.Fatalf("converted cassette =\n%s", content)
	}
}

func headerValues(headers http.Header, name string) []string {
	for candidate, values := range headers {
		if strings.EqualFold(candidate, name) {
			return values
		}
	}
	return nil
}

const secretVCRCassette = `interactions:
  - request:
      method: GET
      uri: https://example.com?api_key=secret
      headers:
        authorization: Bearer secret
      body: null
    response:
      status:
        code: 200
        message: OK
      headers:
        content-type: application/json
      body:
        string: '{"access_token":"secret","value":1}'
`

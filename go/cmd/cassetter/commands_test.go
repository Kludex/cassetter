package main_test

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestCLIInspectDiffAndScrub(t *testing.T) {
	t.Parallel()
	directory := t.TempDir()
	input := filepath.Join(directory, "input.yaml")
	output := filepath.Join(directory, "output.yaml")
	content := `version: 1
interactions:
  - request:
      method: GET
      uri: https://example.com?api_key=secret
      headers:
        authorization:
          - Bearer secret
      body:
        type: none
    response:
      status: 200
      headers: {}
      body:
        type: json
        content:
          access_token: secret
`
	if err := os.WriteFile(input, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	inspect := runCLI(t, "inspect", input)
	if !strings.Contains(inspect, "1. GET https://example.com?api_key=secret -> 200") {
		t.Fatalf("inspect output = %q", inspect)
	}
	runCLI(t, "scrub", input, output)
	scrubbed, err := os.ReadFile(output)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(scrubbed), "secret") || !strings.Contains(string(scrubbed), "[FILTERED]") {
		t.Fatalf("scrubbed cassette = %s", scrubbed)
	}
	difference := runCLIStatus(t, 1, "diff", input, output)
	if !strings.Contains(difference, "--- "+input) || !strings.Contains(difference, "+++ "+output) {
		t.Fatalf("diff output = %q", difference)
	}
	if equal := runCLI(t, "diff", output, output); equal != "No differences.\n" {
		t.Fatalf("equal diff output = %q", equal)
	}
}

func runCLI(t *testing.T, arguments ...string) string {
	t.Helper()
	return runCLIStatus(t, 0, arguments...)
}

func runCLIStatus(t *testing.T, expected int, arguments ...string) string {
	t.Helper()
	command := exec.Command("go", append([]string{"run", "."}, arguments...)...)
	output, err := command.CombinedOutput()
	status := 0
	if exitError, ok := err.(*exec.ExitError); ok {
		status = exitError.ExitCode()
	} else if err != nil {
		t.Fatalf("cassetter %s: %v\n%s", strings.Join(arguments, " "), err, output)
	}
	if status != expected {
		t.Fatalf("cassetter %s exited with %d, expected %d\n%s", strings.Join(arguments, " "), status, expected, output)
	}
	return string(output)
}

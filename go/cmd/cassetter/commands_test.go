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
grpc_interactions:
  - request:
      method: /example.Service/Get
      metadata:
        authorization:
          - Bearer secret
      body:
        type: none
    response:
      status_code: 0
      status_message: OK
      metadata: {}
      body:
        type: none
    json_debug:
      password: secret
ws_interactions:
  - uri: wss://example.com/stream?token=secret
    headers: {}
    frames:
      - direction: send
        frame_type: text
        body:
          type: json
          content:
            client_secret: secret
        offset_ms: 0
`
	if err := os.WriteFile(input, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	inspect := runCLI(t, "inspect", input)
	if !strings.Contains(inspect, "1. GET https://example.com?api_key=secret -> 200") ||
		!strings.Contains(inspect, "1. /example.Service/Get -> 0 OK") ||
		!strings.Contains(inspect, "1. wss://example.com/stream?token=secret -> 1 frame(s)") {
		t.Fatalf("inspect output = %q", inspect)
	}
	runCLI(t, "scrub", input, output)
	scrubbed, err := os.ReadFile(output)
	if err != nil {
		t.Fatal(err)
	}
	scrubbedText := string(scrubbed)
	if strings.Contains(scrubbedText, "Bearer secret") || strings.Contains(scrubbedText, "=secret") ||
		strings.Contains(scrubbedText, ": secret\n") || !strings.Contains(scrubbedText, "[FILTERED]") {
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

package cassetter_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/Kludex/cassetter/go"
)

func TestCassetteReadsYAMLTimestampAsJSONString(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "cassette.yaml")
	content := `version: 1
interactions:
  - request:
      method: POST
      uri: https://example.com
      body:
        type: json
        content:
          date: 2026-01-02
    response:
      status: 200
      body:
        type: none
`
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	cassette, err := cassetter.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	value := cassette.Interactions[0].Request.Body.Content.(map[string]any)["date"]
	if value != "2026-01-02" {
		t.Fatalf("date = %#v", value)
	}
}

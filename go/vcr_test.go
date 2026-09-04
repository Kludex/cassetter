package cassetter_test

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/Kludex/cassetter/go"
)

func TestCassettePreservesLargeVCRJSONInteger(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "vcr.yaml")
	content := `interactions:
  - request:
      method: POST
      uri: https://example.com
      body:
        string: '{"id":18446744073709551616}'
    response:
      status:
        code: 200
      body: null
`
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	cassette, err := cassetter.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	identifier := cassette.Interactions[0].Request.Body.Content.(map[string]any)["id"]
	if fmt.Sprint(identifier) != "18446744073709551616" {
		t.Fatalf("identifier = %v", identifier)
	}
	if err := cassette.Save(path); err != nil {
		t.Fatal(err)
	}
	reloaded, err := cassetter.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	identifier = reloaded.Interactions[0].Request.Body.Content.(map[string]any)["id"]
	if fmt.Sprint(identifier) != "18446744073709551616" {
		t.Fatalf("reloaded identifier = %v", identifier)
	}
}

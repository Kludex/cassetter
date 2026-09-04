package cassetter_test

import (
	"encoding/json"
	"os"
	"testing"
)

func loadJSONFixture[T any](t *testing.T, path string) T {
	t.Helper()
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var value T
	if err := json.Unmarshal(content, &value); err != nil {
		t.Fatal(err)
	}
	return value
}

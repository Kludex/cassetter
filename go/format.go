package cassetter

import (
	"path/filepath"
	"strings"
)

func isTOML(path string) bool {
	return strings.EqualFold(filepath.Ext(path), ".toml")
}

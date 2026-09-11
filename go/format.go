package cassetter

import (
	"fmt"
	"path/filepath"
	"strings"
)

func isTOML(path string) bool {
	return strings.EqualFold(filepath.Ext(path), ".toml")
}

func normalizeCassetteExtension(value string) (string, error) {
	extension := strings.ToLower(strings.TrimPrefix(value, "."))
	switch extension {
	case "yaml", "yml", "toml":
		return extension, nil
	default:
		return "", fmt.Errorf("cassetter: cassette_extension must be one of toml, yaml, yml, got %q", value)
	}
}

func applyCassetteExtension(path string, extension string) string {
	existing := strings.ToLower(strings.TrimPrefix(filepath.Ext(path), "."))
	switch existing {
	case "yaml", "yml", "toml":
		return path
	default:
		return path + "." + extension
	}
}

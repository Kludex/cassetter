package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/Kludex/cassetter/go"
)

func convertFile(input string, output string, scrub bool) (int, error) {
	cassette, err := cassetter.Load(input)
	if err != nil {
		return 0, err
	}
	if scrub {
		cassette.Scrub(cassetter.DefaultSecurityConfig())
	}
	if err := cassette.Save(output); err != nil {
		return 0, err
	}
	return len(cassette.Interactions) + len(cassette.GRPCInteractions) + len(cassette.WebSocketInteractions), nil
}

func requireConversionOutput(input string, output string, force bool) error {
	if samePath(input, output) {
		if !force {
			return fmt.Errorf("converting %s in place requires --force", input)
		}
		return nil
	}
	if _, err := os.Stat(output); err == nil {
		if !force {
			return fmt.Errorf("%s already exists; use --force to overwrite", output)
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("inspect output: %w", err)
	}
	return nil
}

func bareTargetFormat(output string) (string, bool) {
	if filepath.Base(output) != output {
		return "", false
	}
	format := strings.TrimPrefix(strings.ToLower(output), ".")
	if format == "yaml" || format == "yml" || format == "toml" {
		return format, true
	}
	extension := strings.TrimPrefix(strings.ToLower(filepath.Ext(output)), ".")
	return extension, extension == "yaml" || extension == "yml" || extension == "toml"
}

func isCassettePath(path string) bool {
	switch strings.ToLower(filepath.Ext(path)) {
	case ".yaml", ".yml", ".toml":
		return true
	default:
		return false
	}
}

func samePath(left string, right string) bool {
	leftAbsolute, leftErr := filepath.Abs(left)
	rightAbsolute, rightErr := filepath.Abs(right)
	return leftErr == nil && rightErr == nil && leftAbsolute == rightAbsolute
}

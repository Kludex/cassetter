package main

import (
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
)

var errConversionFailures = errors.New("one or more cassette conversions failed")

func convertCommand(arguments []string, stdout io.Writer, stderr io.Writer) error {
	paths := make([]string, 0, 2)
	force := false
	noScrub := false
	targetFormat := ""
	for index := 0; index < len(arguments); index++ {
		switch argument := arguments[index]; {
		case argument == "--force" || argument == "-f":
			force = true
		case argument == "--no-scrub":
			noScrub = true
		case argument == "--to":
			index++
			if index >= len(arguments) {
				return errors.New("--to requires a format")
			}
			targetFormat = arguments[index]
		case strings.HasPrefix(argument, "--to="):
			targetFormat = strings.TrimPrefix(argument, "--to=")
		case strings.HasPrefix(argument, "-"):
			return fmt.Errorf("unknown convert flag %q", argument)
		default:
			paths = append(paths, argument)
		}
	}
	if len(paths) != 2 {
		return errors.New("usage: cassetter convert [flags] <input> <output>")
	}
	if targetFormat != "" && targetFormat != "yaml" && targetFormat != "toml" {
		return fmt.Errorf("unsupported target format %q", targetFormat)
	}
	inputInfo, err := os.Stat(paths[0])
	if err != nil {
		return fmt.Errorf("inspect input: %w", err)
	}
	if inputInfo.IsDir() {
		return convertDirectory(paths[0], paths[1], targetFormat, force, !noScrub, stdout, stderr)
	}
	if targetFormat != "" {
		return errors.New("--to is only valid when the input is a directory")
	}
	if err := requireConversionOutput(paths[0], paths[1], force); err != nil {
		return err
	}
	total, err := convertFile(paths[0], paths[1], !noScrub)
	if err != nil {
		return fmt.Errorf("convert %s: %w", paths[0], err)
	}
	if _, err := fmt.Fprintf(stdout, "Converted %d interaction(s): %s -> %s\n", total, paths[0], paths[1]); err != nil {
		return fmt.Errorf("write output: %w", err)
	}
	return nil
}

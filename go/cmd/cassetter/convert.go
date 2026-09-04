package main

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
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

func convertDirectory(
	input string,
	output string,
	targetFormat string,
	force bool,
	scrub bool,
	stdout io.Writer,
	stderr io.Writer,
) error {
	outputRoot := output
	targetExtension := ""
	if format, ok := bareTargetFormat(output); ok {
		outputRoot = input
		if targetFormat != "" {
			format = targetFormat
		}
		targetExtension = "." + format
	} else if targetFormat != "" {
		targetExtension = "." + targetFormat
	}
	var sources []string
	if err := filepath.WalkDir(input, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if !entry.IsDir() && isCassettePath(path) && !strings.Contains(entry.Name(), ".tmp.") {
			sources = append(sources, path)
		}
		return nil
	}); err != nil {
		return fmt.Errorf("walk input: %w", err)
	}
	sort.Strings(sources)
	if len(sources) == 0 {
		return fmt.Errorf("no cassette files found in %s", input)
	}
	converted := 0
	failed := 0
	for _, source := range sources {
		relative, err := filepath.Rel(input, source)
		if err != nil {
			return err
		}
		destination := filepath.Join(outputRoot, relative)
		if targetExtension != "" {
			destination = strings.TrimSuffix(destination, filepath.Ext(destination)) + targetExtension
		}
		if err := requireConversionOutput(source, destination, force); err != nil {
			if _, writeErr := fmt.Fprintf(stderr, "skip: %v\n", err); writeErr != nil {
				return fmt.Errorf("write output: %w", writeErr)
			}
			continue
		}
		total, err := convertFile(source, destination, scrub)
		if err != nil {
			failed++
			if _, writeErr := fmt.Fprintf(stderr, "error: %s: %v\n", source, err); writeErr != nil {
				return fmt.Errorf("write output: %w", writeErr)
			}
			continue
		}
		converted++
		if _, err := fmt.Fprintf(stdout, "%s -> %s (%d interaction(s))\n", relative, destination, total); err != nil {
			return fmt.Errorf("write output: %w", err)
		}
	}
	if _, err := fmt.Fprintf(stdout, "Converted %d file(s), failed %d\n", converted, failed); err != nil {
		return fmt.Errorf("write output: %w", err)
	}
	if failed > 0 {
		return errConversionFailures
	}
	return nil
}

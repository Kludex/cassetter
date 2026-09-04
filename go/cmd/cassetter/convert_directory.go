package main

import (
	"fmt"
	"io"
	"io/fs"
	"path/filepath"
	"sort"
	"strings"
)

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
	inputAbsolute, err := filepath.Abs(input)
	if err != nil {
		return fmt.Errorf("resolve input: %w", err)
	}
	outputAbsolute, err := filepath.Abs(outputRoot)
	if err != nil {
		return fmt.Errorf("resolve output: %w", err)
	}
	outputRelative, err := filepath.Rel(inputAbsolute, outputAbsolute)
	if err != nil {
		return fmt.Errorf("compare input and output: %w", err)
	}
	outputIsNested := outputRelative != "." && outputRelative != ".." &&
		!strings.HasPrefix(outputRelative, ".."+string(filepath.Separator))
	var sources []string
	if err := filepath.WalkDir(input, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		pathAbsolute, err := filepath.Abs(path)
		if err != nil {
			return err
		}
		if entry.IsDir() && outputIsNested && strings.EqualFold(pathAbsolute, outputAbsolute) {
			return fs.SkipDir
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
	type conversionPlan struct {
		source      string
		destination string
		relative    string
	}
	plans := make([]conversionPlan, 0, len(sources))
	destinations := make(map[string]string, len(sources))
	for _, source := range sources {
		relative, err := filepath.Rel(input, source)
		if err != nil {
			return err
		}
		destination := filepath.Join(outputRoot, relative)
		if targetExtension != "" {
			destination = strings.TrimSuffix(destination, filepath.Ext(destination)) + targetExtension
		}
		destinationAbsolute, err := filepath.Abs(destination)
		if err != nil {
			return fmt.Errorf("resolve destination: %w", err)
		}
		destinationKey := strings.ToLower(filepath.Clean(destinationAbsolute))
		if previous, found := destinations[destinationKey]; found {
			return fmt.Errorf("sources %s and %s map to the same destination %s", previous, source, destination)
		}
		destinations[destinationKey] = source
		plans = append(plans, conversionPlan{source: source, destination: destination, relative: relative})
	}
	converted := 0
	failed := 0
	for _, plan := range plans {
		if err := requireConversionOutput(plan.source, plan.destination, force); err != nil {
			if _, writeErr := fmt.Fprintf(stderr, "skip: %v\n", err); writeErr != nil {
				return fmt.Errorf("write output: %w", writeErr)
			}
			continue
		}
		total, err := convertFile(plan.source, plan.destination, scrub)
		if err != nil {
			failed++
			if _, writeErr := fmt.Fprintf(stderr, "error: %s: %v\n", plan.source, err); writeErr != nil {
				return fmt.Errorf("write output: %w", writeErr)
			}
			continue
		}
		converted++
		if _, err := fmt.Fprintf(
			stdout,
			"%s -> %s (%d interaction(s))\n",
			plan.relative,
			plan.destination,
			total,
		); err != nil {
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

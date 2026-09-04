package main

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"strings"

	"github.com/Kludex/cassetter/go"
	"github.com/pmezard/go-difflib/difflib"
	"gopkg.in/yaml.v3"
)

var errDifferences = errors.New("cassettes differ")

func inspectCommand(arguments []string, stdout io.Writer) error {
	if len(arguments) != 1 {
		return errors.New("usage: cassetter inspect <cassette>")
	}
	cassette, err := cassetter.Load(arguments[0])
	if err != nil {
		return err
	}
	var output strings.Builder
	fmt.Fprintf(&output, "Cassette: %s\n", arguments[0])
	fmt.Fprintf(&output, "Version: %d\n", cassette.Version)
	fmt.Fprintf(&output, "HTTP interactions: %d\n", len(cassette.Interactions))
	for index, interaction := range cassette.Interactions {
		fmt.Fprintf(
			&output,
			"%d. %s %s -> %d",
			index+1,
			interaction.Request.Method,
			interaction.Request.URI,
			interaction.Response.Status,
		)
		if interaction.RecordedAt != "" {
			fmt.Fprintf(&output, " (%s)", interaction.RecordedAt)
		}
		output.WriteByte('\n')
	}
	if _, err := io.WriteString(stdout, output.String()); err != nil {
		return fmt.Errorf("write output: %w", err)
	}
	return nil
}

func diffCommand(arguments []string, stdout io.Writer) error {
	if len(arguments) != 2 {
		return errors.New("usage: cassetter diff <left> <right>")
	}
	left, err := canonicalYAML(arguments[0])
	if err != nil {
		return err
	}
	right, err := canonicalYAML(arguments[1])
	if err != nil {
		return err
	}
	if bytes.Equal(left, right) {
		if _, err := fmt.Fprintln(stdout, "No differences."); err != nil {
			return fmt.Errorf("write output: %w", err)
		}
		return nil
	}
	difference, err := difflib.GetUnifiedDiffString(difflib.UnifiedDiff{
		A:        difflib.SplitLines(string(left)),
		B:        difflib.SplitLines(string(right)),
		FromFile: arguments[0],
		ToFile:   arguments[1],
		Context:  3,
	})
	if err != nil {
		return fmt.Errorf("create diff: %w", err)
	}
	if _, err := fmt.Fprint(stdout, difference); err != nil {
		return fmt.Errorf("write output: %w", err)
	}
	return errDifferences
}

func canonicalYAML(path string) ([]byte, error) {
	cassette, err := cassetter.Load(path)
	if err != nil {
		return nil, err
	}
	content, err := yaml.Marshal(cassette)
	if err != nil {
		return nil, fmt.Errorf("marshal cassette: %w", err)
	}
	return content, nil
}

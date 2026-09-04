package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/Kludex/cassetter/go"
)

type stringValues []string

func (values *stringValues) String() string {
	return strings.Join(*values, ",")
}

func (values *stringValues) Set(value string) error {
	*values = append(*values, value)
	return nil
}

func scrubCommand(arguments []string, stdout io.Writer, stderr io.Writer) error {
	flags := flag.NewFlagSet("scrub", flag.ContinueOnError)
	flags.SetOutput(stderr)
	var headers stringValues
	var queries stringValues
	var bodyPatterns stringValues
	var replacement string
	var force bool
	flags.Var(&headers, "header", "additional header name to remove; repeatable")
	flags.Var(&queries, "query", "additional query parameter to replace; repeatable")
	flags.Var(&bodyPatterns, "body-pattern", "additional JSON key pattern to replace; repeatable")
	flags.StringVar(&replacement, "replacement", "[FILTERED]", "replacement for filtered values")
	flags.BoolVar(&force, "force", false, "overwrite a separate output file")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	paths := flags.Args()
	if len(paths) < 1 || len(paths) > 2 {
		return errors.New("usage: cassetter scrub [flags] <input> [output]")
	}
	input := paths[0]
	output := input
	if len(paths) == 2 {
		output = paths[1]
	}
	if output != input && !force {
		if _, err := os.Stat(output); err == nil {
			return fmt.Errorf("%s already exists; use --force to overwrite", output)
		} else if !errors.Is(err, os.ErrNotExist) {
			return fmt.Errorf("inspect output: %w", err)
		}
	}
	cassette, err := cassetter.Load(input)
	if err != nil {
		return err
	}
	config := cassetter.DefaultSecurityConfig()
	config.FilterHeaders = append(config.FilterHeaders, headers...)
	config.FilterQueryParameters = append(config.FilterQueryParameters, queries...)
	config.BodyScrubPatterns = append(config.BodyScrubPatterns, bodyPatterns...)
	config.Replacement = replacement
	cassette.Scrub(config)
	if err := cassette.Save(output); err != nil {
		return err
	}
	message := fmt.Sprintf("Scrubbed %d HTTP interaction(s): %s\n", len(cassette.Interactions), output)
	if _, err := fmt.Fprint(stdout, message); err != nil {
		return fmt.Errorf("write output: %w", err)
	}
	return nil
}

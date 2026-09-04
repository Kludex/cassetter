package main

import (
	"errors"
	"fmt"
	"io"
	"os"
)

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}

func run(arguments []string, stdout io.Writer, stderr io.Writer) int {
	if len(arguments) == 0 {
		if err := printUsage(stderr); err != nil {
			return 1
		}
		return 2
	}
	var err error
	switch arguments[0] {
	case "inspect":
		err = inspectCommand(arguments[1:], stdout)
	case "diff":
		err = diffCommand(arguments[1:], stdout)
	case "scrub":
		err = scrubCommand(arguments[1:], stdout, stderr)
	case "help", "-h", "--help":
		if err := printUsage(stdout); err != nil {
			return 1
		}
		return 0
	default:
		if _, err := fmt.Fprintf(stderr, "error: unknown command %q\n", arguments[0]); err != nil {
			return 1
		}
		if err := printUsage(stderr); err != nil {
			return 1
		}
		return 2
	}
	if errors.Is(err, errDifferences) {
		return 1
	}
	if err != nil {
		_, _ = fmt.Fprintf(stderr, "error: %v\n", err)
		return 1
	}
	return 0
}

func printUsage(writer io.Writer) error {
	_, err := fmt.Fprintln(writer, `usage: cassetter <inspect|diff|scrub> [arguments]
  inspect <cassette>             summarize recorded interactions
  diff <left> <right>            compare cassettes semantically
  scrub [flags] <input> [output] remove secrets from a cassette`)
	return err
}

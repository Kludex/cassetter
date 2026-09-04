package cassetter

import (
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"
)

// RecordMode controls whether a transport replays or records requests.
type RecordMode string

const (
	// RecordModeNone only replays existing interactions.
	RecordModeNone RecordMode = "none"
	// RecordModeOnce records when the cassette does not exist and otherwise only replays.
	RecordModeOnce RecordMode = "once"
	// RecordModeNewEpisodes replays matches and records misses.
	RecordModeNewEpisodes RecordMode = "new_episodes"
	// RecordModeAll records every request and replaces existing interactions.
	RecordModeAll RecordMode = "all"
	// RecordModeRewrite removes the cassette before recording every request.
	RecordModeRewrite RecordMode = "rewrite"
)

// ErrNoMatch identifies a request that cannot be replayed in the selected mode.
var ErrNoMatch = errors.New("no matching cassette interaction")

// NoMatchError describes a request that has no unused matching interaction.
type NoMatchError struct {
	Method string
	URI    string
}

// Error implements error.
func (e *NoMatchError) Error() string {
	return fmt.Sprintf("%s for %s %s", ErrNoMatch, e.Method, e.URI)
}

// Unwrap allows errors.Is(err, ErrNoMatch).
func (e *NoMatchError) Unwrap() error {
	return ErrNoMatch
}

// Option configures a Transport.
type Option interface {
	apply(*transportConfig)
}

type optionFunc func(*transportConfig)

func (option optionFunc) apply(config *transportConfig) {
	option(config)
}

type transportConfig struct {
	path            string
	mode            RecordMode
	security        SecurityConfig
	matchers        []Matcher
	ignoreJSONPaths []string
	uriNormalizer   func(string) string
	maxAge          *time.Duration
	expiryAction    ExpiryAction
	ignoreLocalhost bool
	ignoreHosts     []string
	requestHook     RequestHook
	responseHook    ResponseHook
}

// WithPath sets the YAML cassette path.
func WithPath(path string) Option {
	return optionFunc(func(config *transportConfig) {
		config.path = path
	})
}

// WithRecordMode sets recording and replay behavior.
func WithRecordMode(mode RecordMode) Option {
	return optionFunc(func(config *transportConfig) {
		config.mode = mode
	})
}

// WithFilterHeaders adds header names to the safe defaults.
func WithFilterHeaders(names ...string) Option {
	return optionFunc(func(config *transportConfig) {
		config.security.FilterHeaders = appendUniqueFold(config.security.FilterHeaders, names...)
	})
}

// WithFilterQueryParameters adds query parameter names to the safe defaults.
func WithFilterQueryParameters(names ...string) Option {
	return optionFunc(func(config *transportConfig) {
		config.security.FilterQueryParameters = appendUniqueFold(
			config.security.FilterQueryParameters,
			names...,
		)
	})
}

// WithBodyScrubPatterns adds JSON key patterns to the safe defaults.
func WithBodyScrubPatterns(patterns ...string) Option {
	return optionFunc(func(config *transportConfig) {
		config.security.BodyScrubPatterns = appendUniqueFold(config.security.BodyScrubPatterns, patterns...)
	})
}

// WithFilterReplacement changes the value written in place of secrets.
func WithFilterReplacement(replacement string) Option {
	return optionFunc(func(config *transportConfig) {
		config.security.Replacement = replacement
	})
}

// NewTransport wraps base with cassette recording and replay.
func NewTransport(base http.RoundTripper, options ...Option) *Transport {
	if base == nil {
		base = http.DefaultTransport
	}
	config := transportConfig{
		mode:         RecordModeOnce,
		security:     DefaultSecurityConfig(),
		matchers:     []Matcher{MatcherMethod, MatcherURI},
		expiryAction: ExpiryWarn,
	}
	for _, option := range options {
		option.apply(&config)
	}
	return &Transport{base: base, config: config}
}

func appendUniqueFold(current []string, values ...string) []string {
	for _, value := range values {
		found := false
		for _, existing := range current {
			if strings.EqualFold(existing, value) {
				found = true
				break
			}
		}
		if !found {
			current = append(current, value)
		}
	}
	return current
}

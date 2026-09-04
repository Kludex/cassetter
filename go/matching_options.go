package cassetter

// WithMatchers replaces the request fields used for matching.
func WithMatchers(matchers ...Matcher) Option {
	return optionFunc(func(config *transportConfig) {
		config.matchers = append([]Matcher(nil), matchers...)
	})
}

// WithIgnoredJSONPaths sets JSON paths ignored by the JSON body matcher.
func WithIgnoredJSONPaths(paths ...string) Option {
	return optionFunc(func(config *transportConfig) {
		config.ignoreJSONPaths = append([]string(nil), paths...)
	})
}

// WithURINormalizer changes URIs only for request comparison.
func WithURINormalizer(normalizer func(string) string) Option {
	return optionFunc(func(config *transportConfig) {
		config.uriNormalizer = normalizer
	})
}

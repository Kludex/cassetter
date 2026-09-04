package cassetter

import "time"

// WithMaxAge marks cassettes older than maxAge as expired.
func WithMaxAge(maxAge time.Duration) Option {
	return optionFunc(func(config *transportConfig) {
		config.maxAge = &maxAge
	})
}

// WithExpiryAction sets how an expired cassette is handled.
func WithExpiryAction(action ExpiryAction) Option {
	return optionFunc(func(config *transportConfig) {
		config.expiryAction = action
	})
}

// WithIgnoreLocalhost bypasses recording and replay for localhost traffic.
func WithIgnoreLocalhost() Option {
	return optionFunc(func(config *transportConfig) {
		config.ignoreLocalhost = true
	})
}

// WithIgnoreHosts bypasses recording and replay for matching host patterns.
func WithIgnoreHosts(patterns ...string) Option {
	return optionFunc(func(config *transportConfig) {
		config.ignoreHosts = append(config.ignoreHosts, patterns...)
	})
}

// WithRequestHook sets a hook that runs before request matching and recording.
func WithRequestHook(hook RequestHook) Option {
	return optionFunc(func(config *transportConfig) {
		config.requestHook = hook
	})
}

// WithResponseHook sets a hook that runs on live responses before recording.
func WithResponseHook(hook ResponseHook) Option {
	return optionFunc(func(config *transportConfig) {
		config.responseHook = hook
	})
}

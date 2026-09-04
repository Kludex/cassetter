package cassetter

import (
	"fmt"
	"net/url"
	"path"
	"strings"
)

func validateIgnoreHosts(patterns []string) error {
	for _, pattern := range patterns {
		if _, err := path.Match(pattern, ""); err != nil {
			return fmt.Errorf("cassetter: invalid ignored host pattern %q: %w", pattern, err)
		}
	}
	return nil
}

func (t *Transport) shouldBypass(target *url.URL) bool {
	host := target.Hostname()
	if t.config.ignoreLocalhost && (strings.EqualFold(host, "localhost") || host == "127.0.0.1" || host == "::1") {
		return true
	}
	for _, pattern := range t.config.ignoreHosts {
		if matched, _ := path.Match(pattern, host); matched {
			return true
		}
	}
	return false
}

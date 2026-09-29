package cassetter

import (
	"net/http"
	"slices"
	"testing"
)

func TestFilterHeadersPatternsAndExceptions(t *testing.T) {
	tests := []struct {
		name     string
		filtered []string
		kept     []string
	}{
		{"exact names ignore case", []string{"AUTHORIZATION"}, []string{"Anthropic-Organization-Id", "Content-Type", "X-Amzn-Bedrock-Input-Token-Count", "X-Request-Id"}},
		{"a prefix pattern", []string{"x-*"}, []string{"Anthropic-Organization-Id", "Authorization", "Content-Type"}},
		{"a pattern in the middle", []string{"anthropic-*-id"}, []string{"Authorization", "Content-Type", "X-Amzn-Bedrock-Input-Token-Count", "X-Request-Id"}},
		{"an exception keeps what another entry removes", []string{"x-*", "!X-Amzn-Bedrock-*"}, []string{"Anthropic-Organization-Id", "Authorization", "Content-Type", "X-Amzn-Bedrock-Input-Token-Count"}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			headers := http.Header{}
			for _, name := range []string{"Authorization", "X-Request-Id", "X-Amzn-Bedrock-Input-Token-Count", "Anthropic-Organization-Id", "Content-Type"} {
				headers[name] = []string{"v"}
			}
			filterHeaders(headers, test.filtered)
			kept := make([]string, 0, len(headers))
			for name := range headers {
				kept = append(kept, name)
			}
			slices.Sort(kept)
			if !slices.Equal(kept, test.kept) {
				t.Fatalf("kept %v, want %v", kept, test.kept)
			}
		})
	}
}

func TestGlobMatch(t *testing.T) {
	tests := []struct {
		pattern, name string
		want          bool
	}{
		{"x-*", "x-", true},
		{"*", "anything", true},
		{"a*b*c", "abxbc", true},
		{"exact", "exact", true},
		{"exact", "exactly", false},
		{"a*bc", "abc-b", false},
		{"ab*ba", "aba", false},
		{"x-*", "y-x-", false},
	}
	for _, test := range tests {
		if got := globMatch(test.pattern, test.name); got != test.want {
			t.Errorf("globMatch(%q, %q) = %v, want %v", test.pattern, test.name, got, test.want)
		}
	}
}

package cassetter_test

import (
	"path/filepath"
	"testing"

	"github.com/Kludex/cassetter/go"
)

type filteringCase struct {
	Name                  string   `json:"name"`
	FilterHeaders         []string `json:"filterHeaders"`
	FilterQueryParameters []string `json:"filterQueryParameters"`
	BodyScrubPatterns     []string `json:"bodyScrubPatterns"`
	Replacement           string   `json:"replacement"`
	Expected              string   `json:"expected"`
}

func TestFilteringConformance(t *testing.T) {
	t.Parallel()
	fixtures := filepath.Join(conformanceFixtures(t), "filtering")
	cases := loadJSONFixture[[]filteringCase](t, filepath.Join(fixtures, "cases.json"))
	for _, testCase := range cases {
		t.Run(testCase.Name, func(t *testing.T) {
			t.Parallel()
			cassette, err := cassetter.Load(filepath.Join(fixtures, "input.yaml"))
			if err != nil {
				t.Fatal(err)
			}
			config := cassetter.DefaultSecurityConfig()
			config.FilterHeaders = append(config.FilterHeaders, testCase.FilterHeaders...)
			config.FilterQueryParameters = append(
				config.FilterQueryParameters,
				testCase.FilterQueryParameters...,
			)
			config.BodyScrubPatterns = append(config.BodyScrubPatterns, testCase.BodyScrubPatterns...)
			if testCase.Replacement != "" {
				config.Replacement = testCase.Replacement
			}
			cassette.Scrub(config)
			assertCanonicalJSON(t, canonicalCassette(cassette), filepath.Join(fixtures, testCase.Expected))
		})
	}
}

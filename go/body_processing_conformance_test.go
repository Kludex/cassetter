package cassetter_test

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"path/filepath"
	"testing"

	"github.com/Kludex/cassetter/go"
)

func TestBodyProcessingConformance(t *testing.T) {
	t.Parallel()
	fixtures := filepath.Join(conformanceFixtures(t), "body-processing")
	source, err := cassetter.Load(filepath.Join(fixtures, "cases.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	interactions := make(map[string]cassetter.HTTPInteraction, len(source.Interactions))
	for _, interaction := range source.Interactions {
		interactions[interaction.Request.URI] = interaction
	}
	base := roundTripFunc(func(request *http.Request) (*http.Response, error) {
		interaction, found := interactions[request.URL.String()]
		if !found {
			return nil, fmt.Errorf("unexpected body processing URI %q", request.URL)
		}
		content, err := conformanceBodyBytes(interaction.Response.Body)
		if err != nil {
			return nil, err
		}
		return &http.Response{
			StatusCode: interaction.Response.Status,
			Header:     interaction.Response.Headers.Clone(),
			Body:       io.NopCloser(bytes.NewReader(content)),
			Request:    request,
		}, nil
	})
	path := filepath.Join(t.TempDir(), "recorded.yaml")
	transport := cassetter.NewTransport(
		base,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeAll),
	)
	client := &http.Client{Transport: transport}
	for _, interaction := range source.Interactions {
		response, err := client.Get(interaction.Request.URI)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := io.Copy(io.Discard, response.Body); err != nil {
			t.Fatal(err)
		}
		if err := response.Body.Close(); err != nil {
			t.Fatal(err)
		}
	}
	if err := transport.Close(); err != nil {
		t.Fatal(err)
	}

	recorded, err := cassetter.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	actual := make(map[string]any, len(recorded.Interactions))
	for _, interaction := range recorded.Interactions {
		actual[interaction.Request.URI] = canonicalBody(interaction.Response.Body)
	}
	assertCanonicalJSON(t, actual, filepath.Join(fixtures, "expected.json"))
}

func conformanceBodyBytes(body cassetter.Body) ([]byte, error) {
	switch body.Type {
	case "", cassetter.BodyTypeNone:
		return nil, nil
	case cassetter.BodyTypeJSON:
		return json.Marshal(body.Content)
	case cassetter.BodyTypeText:
		return []byte(body.Content.(string)), nil
	case cassetter.BodyTypeBinary:
		return append([]byte(nil), body.Content.([]byte)...), nil
	default:
		return nil, fmt.Errorf("unknown conformance body type %q", body.Type)
	}
}

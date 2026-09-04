package cassetter

import (
	"fmt"

	"github.com/pelletier/go-toml/v2"
)

func unmarshalTOML(content []byte) (*Cassette, error) {
	var raw tomlCassette
	if err := toml.Unmarshal(content, &raw); err != nil {
		return nil, fmt.Errorf("parse TOML cassette: %w", err)
	}
	if raw.Version == 0 {
		return nil, fmt.Errorf("TOML cassette version is required")
	}
	cassette := &Cassette{Version: raw.Version, Interactions: make([]HTTPInteraction, 0, len(raw.Interactions))}
	for index, interaction := range raw.Interactions {
		requestBody, err := bodyFromTOML(interaction.Request.BodyType, interaction.Request.BodyContent)
		if err != nil {
			return nil, fmt.Errorf("invalid TOML request body in interaction %d: %w", index, err)
		}
		responseBody, err := bodyFromTOML(interaction.Response.BodyType, interaction.Response.BodyContent)
		if err != nil {
			return nil, fmt.Errorf("invalid TOML response body in interaction %d: %w", index, err)
		}
		cassette.Interactions = append(cassette.Interactions, HTTPInteraction{
			Request: HTTPRequest{
				Method:  interaction.Request.Method,
				URI:     interaction.Request.URI,
				Headers: interaction.Request.Headers,
				Body:    requestBody,
			},
			Response: HTTPResponse{
				Status:  interaction.Response.Status,
				Headers: interaction.Response.Headers,
				Body:    responseBody,
			},
			RecordedAt: interaction.RecordedAt,
		})
	}
	if err := cassette.validate(); err != nil {
		return nil, err
	}
	return cassette, nil
}

func (c *Cassette) marshalTOML() ([]byte, error) {
	if len(c.GRPCInteractions) > 0 || len(c.WebSocketInteractions) > 0 {
		return nil, fmt.Errorf("TOML cassettes cannot store gRPC or WebSocket interactions; use YAML")
	}
	if len(c.extra) > 0 {
		return nil, fmt.Errorf("TOML cassettes cannot store unrecognized top-level sections; use YAML")
	}
	version := c.Version
	if version == 0 {
		version = 1
	}
	raw := tomlCassette{Version: version, Interactions: make([]tomlInteraction, 0, len(c.Interactions))}
	for _, interaction := range c.Interactions {
		requestType, requestContent, err := bodyToTOML(interaction.Request.Body)
		if err != nil {
			return nil, err
		}
		responseType, responseContent, err := bodyToTOML(interaction.Response.Body)
		if err != nil {
			return nil, err
		}
		raw.Interactions = append(raw.Interactions, tomlInteraction{
			Request: tomlRequest{
				Method:      interaction.Request.Method,
				URI:         interaction.Request.URI,
				Headers:     interaction.Request.Headers,
				BodyType:    requestType,
				BodyContent: requestContent,
			},
			Response: tomlResponse{
				Status:      interaction.Response.Status,
				Headers:     interaction.Response.Headers,
				BodyType:    responseType,
				BodyContent: responseContent,
			},
			RecordedAt: interaction.RecordedAt,
		})
	}
	content, err := toml.Marshal(raw)
	if err != nil {
		return nil, fmt.Errorf("marshal TOML cassette: %w", err)
	}
	return content, nil
}

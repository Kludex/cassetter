package cassetter_test

import (
	"encoding/hex"
	"net/http"

	"github.com/Kludex/cassetter/go"
)

func canonicalCassette(cassette *cassetter.Cassette) map[string]any {
	httpInteractions := make([]any, 0, len(cassette.Interactions))
	for _, interaction := range cassette.Interactions {
		httpInteractions = append(httpInteractions, map[string]any{
			"method":          interaction.Request.Method,
			"uri":             interaction.Request.URI,
			"requestHeaders":  canonicalHeaders(interaction.Request.Headers),
			"requestBody":     canonicalBody(interaction.Request.Body),
			"status":          interaction.Response.Status,
			"responseHeaders": canonicalHeaders(interaction.Response.Headers),
			"responseBody":    canonicalBody(interaction.Response.Body),
			"recordedAt":      interaction.RecordedAt,
		})
	}
	grpcInteractions := make([]any, 0, len(cassette.GRPCInteractions))
	for _, interaction := range cassette.GRPCInteractions {
		grpcInteractions = append(grpcInteractions, map[string]any{
			"method":           interaction.Request.Method,
			"metadata":         canonicalHeaders(interaction.Request.Metadata),
			"requestBody":      canonicalBody(interaction.Request.Body),
			"statusCode":       interaction.Response.StatusCode,
			"statusMessage":    interaction.Response.StatusMessage,
			"responseMetadata": canonicalHeaders(interaction.Response.Metadata),
			"responseBody":     canonicalBody(interaction.Response.Body),
			"jsonDebug":        interaction.JSONDebug,
			"recordedAt":       interaction.RecordedAt,
		})
	}
	webSocketInteractions := make([]any, 0, len(cassette.WebSocketInteractions))
	for _, interaction := range cassette.WebSocketInteractions {
		frames := make([]any, 0, len(interaction.Frames))
		for _, frame := range interaction.Frames {
			frames = append(frames, map[string]any{
				"direction": frame.Direction,
				"frameType": frame.FrameType,
				"body":      canonicalBody(frame.Body),
				"offsetMs":  frame.OffsetMS,
			})
		}
		webSocketInteractions = append(webSocketInteractions, map[string]any{
			"uri":        interaction.URI,
			"headers":    canonicalHeaders(interaction.Headers),
			"frames":     frames,
			"recordedAt": interaction.RecordedAt,
		})
	}
	return map[string]any{
		"version": cassette.Version,
		"http":    httpInteractions,
		"grpc":    grpcInteractions,
		"ws":      webSocketInteractions,
	}
}

func canonicalBody(body cassetter.Body) map[string]any {
	result := map[string]any{"type": body.Type}
	if body.Type == cassetter.BodyTypeBinary {
		result["content"] = hex.EncodeToString(body.Content.([]byte))
	} else if body.Type != cassetter.BodyTypeNone {
		result["content"] = body.Content
	}
	return result
}

func canonicalHeaders(headers http.Header) map[string][]string {
	result := make(map[string][]string, len(headers))
	for name, values := range headers {
		result[name] = append([]string{}, values...)
	}
	return result
}

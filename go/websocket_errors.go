package cassetter

import "fmt"

// NoWebSocketMatchError describes a WebSocket connection with no matching interaction.
type NoWebSocketMatchError struct {
	URI string
}

// Error implements error.
func (e *NoWebSocketMatchError) Error() string {
	return fmt.Sprintf("%s for WebSocket URI %s", ErrNoMatch, e.URI)
}

// Unwrap allows errors.Is(err, ErrNoMatch).
func (e *NoWebSocketMatchError) Unwrap() error {
	return ErrNoMatch
}

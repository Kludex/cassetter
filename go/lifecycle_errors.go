package cassetter

import (
	"errors"
	"fmt"
)

// ErrIncompleteRecording identifies a response body that was not fully consumed.
var ErrIncompleteRecording = errors.New("incomplete cassette recording")

// ErrTransportClosed identifies a request sent after Transport.Close.
var ErrTransportClosed = errors.New("cassetter transport is closed")

// IncompleteRecordingError describes a response that could not be recorded completely.
type IncompleteRecordingError struct {
	Method string
	URI    string
}

// Error implements error.
func (e *IncompleteRecordingError) Error() string {
	return fmt.Sprintf("%s for %s %s", ErrIncompleteRecording, e.Method, e.URI)
}

// Unwrap allows errors.Is(err, ErrIncompleteRecording).
func (e *IncompleteRecordingError) Unwrap() error {
	return ErrIncompleteRecording
}

// IncompleteGRPCRecordingError describes a gRPC stream that did not finish.
type IncompleteGRPCRecordingError struct {
	Method string
}

// Error implements error.
func (e *IncompleteGRPCRecordingError) Error() string {
	return fmt.Sprintf("%s for gRPC method %s", ErrIncompleteRecording, e.Method)
}

// Unwrap allows errors.Is(err, ErrIncompleteRecording).
func (e *IncompleteGRPCRecordingError) Unwrap() error {
	return ErrIncompleteRecording
}

// IncompleteWebSocketRecordingError describes a WebSocket connection that did not close.
type IncompleteWebSocketRecordingError struct {
	URI string
}

// Error implements error.
func (e *IncompleteWebSocketRecordingError) Error() string {
	return fmt.Sprintf("%s for WebSocket URI %s", ErrIncompleteRecording, e.URI)
}

// Unwrap allows errors.Is(err, ErrIncompleteRecording).
func (e *IncompleteWebSocketRecordingError) Unwrap() error {
	return ErrIncompleteRecording
}

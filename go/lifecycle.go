package cassetter

import (
	"errors"
	"fmt"
	"net/http"
	"sort"
	"testing"
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

// Initialize loads the cassette before the first request.
func (t *Transport) Initialize() error {
	t.initialize.Do(t.load)
	return t.initErr
}

// Close ends the transport lifecycle and reports recording failures.
func (t *Transport) Close() error {
	if err := t.Initialize(); err != nil {
		return err
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.closed {
		return t.closeErr
	}
	t.closed = true
	err := t.recordErr
	orders := make([]uint64, 0, len(t.pending))
	for order := range t.pending {
		orders = append(orders, order)
	}
	sort.Slice(orders, func(left int, right int) bool {
		return orders[left] < orders[right]
	})
	for _, order := range orders {
		pending := t.pending[order]
		err = errors.Join(err, &IncompleteRecordingError{Method: pending.method, URI: pending.uri})
	}
	grpcOrders := make([]uint64, 0, len(t.grpcPending))
	for order := range t.grpcPending {
		grpcOrders = append(grpcOrders, order)
	}
	sort.Slice(grpcOrders, func(left int, right int) bool {
		return grpcOrders[left] < grpcOrders[right]
	})
	for _, order := range grpcOrders {
		err = errors.Join(err, &IncompleteGRPCRecordingError{Method: t.grpcPending[order]})
	}
	if t.saveEmpty {
		err = errors.Join(err, t.cassette.Save(t.config.path))
		t.saveEmpty = false
	}
	t.closeErr = err
	return err
}

// NewGRPCRecorder creates a transport for gRPC client interceptors.
func NewGRPCRecorder(options ...Option) *Transport {
	return NewTransport(nil, options...)
}

// NewTestGRPCRecorder creates a gRPC recorder whose lifecycle is managed by a Go test.
func NewTestGRPCRecorder(tb testing.TB, options ...Option) *Transport {
	tb.Helper()
	return NewTestTransport(tb, nil, options...)
}

// NewTestTransport creates a transport whose lifecycle is managed by a Go test.
func NewTestTransport(tb testing.TB, base http.RoundTripper, options ...Option) *Transport {
	tb.Helper()
	transport := NewTransport(base, options...)
	if err := transport.Initialize(); err != nil {
		tb.Fatalf("initialize cassetter transport: %v", err)
		return transport
	}
	tb.Cleanup(func() {
		tb.Helper()
		if err := transport.Close(); err != nil {
			tb.Errorf("close cassetter transport: %v", err)
		}
	})
	return transport
}

package cassetter

import (
	"context"
	"errors"
	"fmt"

	"google.golang.org/grpc/status"
)

// NoGRPCMatchError describes a gRPC call with no matching interaction.
type NoGRPCMatchError struct {
	Method string
}

// Error implements error.
func (e *NoGRPCMatchError) Error() string {
	return fmt.Sprintf("%s for gRPC method %s", ErrNoMatch, e.Method)
}

// Unwrap allows errors.Is(err, ErrNoMatch).
func (e *NoGRPCMatchError) Unwrap() error {
	return ErrNoMatch
}

func grpcContextError(ctx context.Context) error {
	if err := ctx.Err(); err != nil {
		return status.FromContextError(err).Err()
	}
	return nil
}

func joinGRPCErrors(callErr error, recordingErr error) error {
	if callErr == nil {
		return recordingErr
	}
	if recordingErr == nil {
		return callErr
	}
	return errors.Join(callErr, recordingErr)
}

package cassetter

import (
	"context"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// StreamClientInterceptor returns a gRPC streaming client interceptor backed by the cassette.
func (t *Transport) StreamClientInterceptor() grpc.StreamClientInterceptor {
	return func(
		ctx context.Context,
		description *grpc.StreamDesc,
		connection *grpc.ClientConn,
		method string,
		streamer grpc.Streamer,
		options ...grpc.CallOption,
	) (grpc.ClientStream, error) {
		return t.interceptStreamGRPC(ctx, description, connection, method, streamer, options...)
	}
}

func (t *Transport) interceptStreamGRPC(
	ctx context.Context,
	description *grpc.StreamDesc,
	connection *grpc.ClientConn,
	method string,
	streamer grpc.Streamer,
	options ...grpc.CallOption,
) (grpc.ClientStream, error) {
	if err := t.Initialize(); err != nil {
		return nil, err
	}
	if err := t.checkOpen(); err != nil {
		return nil, err
	}
	if t.config.mode != RecordModeAll && t.config.mode != RecordModeRewrite {
		interaction, found, err := t.takeGRPCMatch(method)
		if err != nil {
			return nil, err
		}
		if found {
			return newReplayGRPCStream(ctx, interaction.Response, options)
		}
	}
	if !t.canRecord {
		return nil, &NoGRPCMatchError{Method: method}
	}
	order, err := t.reserveGRPCRecording(method)
	if err != nil {
		return nil, err
	}
	stream, streamErr := streamer(ctx, description, connection, method, options...)
	if streamErr != nil {
		t.finishGRPCRecording(order, nil)
		return nil, streamErr
	}
	return &recordingGRPCClientStream{
		ClientStream: stream,
		transport:    t,
		description:  description,
		ctx:          ctx,
		method:       method,
		order:        order,
	}, nil
}

func grpcStreamStatus(terminalError error) (codes.Code, string) {
	if terminalError == nil {
		return codes.OK, "OK"
	}
	statusValue := status.Convert(terminalError)
	return statusValue.Code(), statusValue.Message()
}

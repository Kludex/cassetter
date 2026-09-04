package cassetter_test

import (
	"context"
	"io"
	"net"
	"testing"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	grpc_testing "google.golang.org/grpc/interop/grpc_testing"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"
)

type cassetteTestService struct {
	grpc_testing.UnimplementedTestServiceServer
}

func (cassetteTestService) EmptyCall(context.Context, *grpc_testing.Empty) (*grpc_testing.Empty, error) {
	return nil, status.Error(codes.PermissionDenied, "denied")
}

func (cassetteTestService) UnaryCall(
	ctx context.Context,
	request *grpc_testing.SimpleRequest,
) (*grpc_testing.SimpleResponse, error) {
	if err := grpc.SetHeader(ctx, metadata.Pairs("x-server", "header")); err != nil {
		return nil, err
	}
	if err := grpc.SetTrailer(ctx, metadata.Pairs("x-server-trailer", "trailer")); err != nil {
		return nil, err
	}
	return &grpc_testing.SimpleResponse{Payload: request.Payload}, nil
}

func (cassetteTestService) StreamingOutputCall(
	_ *grpc_testing.StreamingOutputCallRequest,
	stream grpc.ServerStreamingServer[grpc_testing.StreamingOutputCallResponse],
) error {
	if err := stream.SetHeader(metadata.Pairs("x-stream", "header")); err != nil {
		return err
	}
	for _, value := range []string{"first", "second"} {
		response := &grpc_testing.StreamingOutputCallResponse{Payload: grpcPayload(value)}
		if err := stream.Send(response); err != nil {
			return err
		}
	}
	return nil
}

func (cassetteTestService) StreamingInputCall(
	stream grpc.ClientStreamingServer[grpc_testing.StreamingInputCallRequest, grpc_testing.StreamingInputCallResponse],
) error {
	var size int32
	for {
		request, err := stream.Recv()
		if err != nil {
			if err == io.EOF {
				return stream.SendAndClose(&grpc_testing.StreamingInputCallResponse{AggregatedPayloadSize: size})
			}
			return err
		}
		size += int32(len(request.GetPayload().GetBody()))
	}
}

func (cassetteTestService) FullDuplexCall(
	stream grpc.BidiStreamingServer[grpc_testing.StreamingOutputCallRequest, grpc_testing.StreamingOutputCallResponse],
) error {
	for {
		request, err := stream.Recv()
		if err != nil {
			if err == io.EOF {
				return nil
			}
			return err
		}
		if err := stream.Send(&grpc_testing.StreamingOutputCallResponse{Payload: request.Payload}); err != nil {
			return err
		}
	}
}

func (cassetteTestService) HalfDuplexCall(
	grpc.BidiStreamingServer[grpc_testing.StreamingOutputCallRequest, grpc_testing.StreamingOutputCallResponse],
) error {
	return status.Error(codes.ResourceExhausted, "stream denied")
}

func grpcPayload(value string) *grpc_testing.Payload {
	return &grpc_testing.Payload{Body: []byte(value)}
}

func startGRPCTestServer(t *testing.T) (string, func(context.Context, string) (net.Conn, error)) {
	t.Helper()
	listener := bufconn.Listen(1024 * 1024)
	server := grpc.NewServer()
	grpc_testing.RegisterTestServiceServer(server, cassetteTestService{})
	go func() {
		_ = server.Serve(listener)
	}()
	t.Cleanup(func() {
		server.Stop()
		_ = listener.Close()
	})
	return "passthrough:///cassetter-test", func(context.Context, string) (net.Conn, error) {
		return listener.Dial()
	}
}

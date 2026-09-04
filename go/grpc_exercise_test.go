package cassetter_test

import (
	"bytes"
	"context"
	"errors"
	"io"
	"testing"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	grpc_testing "google.golang.org/grpc/interop/grpc_testing"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

func exerciseGRPCClient(t *testing.T, client grpc_testing.TestServiceClient) {
	t.Helper()
	ctx := metadata.NewOutgoingContext(
		context.Background(),
		metadata.Pairs("authorization", "secret", "x-request", "request"),
	)
	var header metadata.MD
	var trailer metadata.MD
	unary, err := client.UnaryCall(ctx, unaryRequest(), grpc.Header(&header), grpc.Trailer(&trailer))
	if err != nil {
		t.Fatalf("unary call: %v", err)
	}
	if got := string(unary.GetPayload().GetBody()); got != "unary" {
		t.Fatalf("unary payload = %q, want unary", got)
	}
	if got := header.Get("x-server"); len(got) != 1 || got[0] != "header" {
		t.Fatalf("unary header = %v, want header", got)
	}
	if got := header.Get("x-binary-bin"); len(got) != 1 || !bytes.Equal([]byte(got[0]), []byte{0xff, 0x00}) {
		t.Fatalf("unary binary header = %q, want ff00", got)
	}
	if got := trailer.Get("x-server-trailer"); len(got) != 1 || got[0] != "trailer" {
		t.Fatalf("unary trailer = %v, want trailer", got)
	}

	_, err = client.EmptyCall(context.Background(), &grpc_testing.Empty{})
	if status.Code(err) != codes.PermissionDenied || status.Convert(err).Message() != "denied" {
		t.Fatalf("empty call error = %v, want permission denied", err)
	}

	serverStream, err := client.StreamingOutputCall(context.Background(), &grpc_testing.StreamingOutputCallRequest{})
	if err != nil {
		t.Fatalf("create server stream: %v", err)
	}
	streamHeader, err := serverStream.Header()
	if err != nil {
		t.Fatalf("read server stream header: %v", err)
	}
	if got := streamHeader.Get("x-stream"); len(got) != 1 || got[0] != "header" {
		t.Fatalf("server stream header = %v, want header", got)
	}
	var serverValues []string
	for {
		response, recvErr := serverStream.Recv()
		if errors.Is(recvErr, io.EOF) {
			break
		}
		if recvErr != nil {
			t.Fatalf("receive server stream: %v", recvErr)
		}
		serverValues = append(serverValues, string(response.GetPayload().GetBody()))
	}
	if len(serverValues) != 2 || serverValues[0] != "first" || serverValues[1] != "second" {
		t.Fatalf("server stream values = %v", serverValues)
	}

	clientStream, err := client.StreamingInputCall(context.Background())
	if err != nil {
		t.Fatalf("create client stream: %v", err)
	}
	for _, value := range []string{"one", "two"} {
		if err := clientStream.Send(&grpc_testing.StreamingInputCallRequest{Payload: grpcPayload(value)}); err != nil {
			t.Fatalf("send client stream: %v", err)
		}
	}
	clientResponse, err := clientStream.CloseAndRecv()
	if err != nil {
		t.Fatalf("close client stream: %v", err)
	}
	if got := clientResponse.GetAggregatedPayloadSize(); got != 6 {
		t.Fatalf("aggregated payload size = %d, want 6", got)
	}

	exerciseBidiGRPCCalls(t, client)
}

func exerciseBidiGRPCCalls(t *testing.T, client grpc_testing.TestServiceClient) {
	t.Helper()
	bidi, err := client.FullDuplexCall(context.Background())
	if err != nil {
		t.Fatalf("create bidi stream: %v", err)
	}
	if err := bidi.Send(&grpc_testing.StreamingOutputCallRequest{Payload: grpcPayload("bidi")}); err != nil {
		t.Fatalf("send bidi stream: %v", err)
	}
	bidiResponse, err := bidi.Recv()
	if err != nil {
		t.Fatalf("receive bidi stream: %v", err)
	}
	if got := string(bidiResponse.GetPayload().GetBody()); got != "bidi" {
		t.Fatalf("bidi payload = %q, want bidi", got)
	}
	if err := bidi.CloseSend(); err != nil {
		t.Fatalf("close bidi send: %v", err)
	}
	_, err = bidi.Recv()
	if !errors.Is(err, io.EOF) {
		t.Fatalf("finish bidi stream: %v", err)
	}

	failedStream, err := client.HalfDuplexCall(context.Background())
	if err != nil {
		t.Fatalf("create failing stream: %v", err)
	}
	_, err = failedStream.Recv()
	if status.Code(err) != codes.ResourceExhausted || status.Convert(err).Message() != "stream denied" {
		t.Fatalf("failing stream error = %v, want resource exhausted", err)
	}
}

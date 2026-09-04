package cassetter_test

import (
	"bytes"
	"context"
	"path/filepath"
	"testing"

	"github.com/Kludex/cassetter/go"
	grpc_testing "google.golang.org/grpc/interop/grpc_testing"
	"google.golang.org/protobuf/proto"
)

func TestGRPCInterceptorsRecordAndReplayUnaryAndStreamingCalls(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "grpc.yaml")
	target, dialer := startGRPCTestServer(t)
	recorder := cassetter.NewGRPCRecorder(
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeAll),
		cassetter.WithBodyScrubPatterns("body"),
	)
	recordingConnection := newGRPCClientConnection(t, target, dialer, recorder)
	exerciseGRPCClient(t, grpc_testing.NewTestServiceClient(recordingConnection))
	if err := recorder.Close(); err != nil {
		t.Fatalf("close recording transport: %v", err)
	}

	cassette, err := cassetter.Load(path)
	if err != nil {
		t.Fatalf("load recorded cassette: %v", err)
	}
	if len(cassette.GRPCInteractions) != 6 {
		t.Fatalf("got %d gRPC interactions, want 6", len(cassette.GRPCInteractions))
	}
	unary := cassette.GRPCInteractions[0]
	if got := grpcHeaderValues(unary.Request.Metadata, "authorization"); len(got) != 0 {
		t.Fatalf("recorded authorization metadata: %v", unary.Request.Metadata)
	}
	if got := grpcHeaderValues(unary.Request.Metadata, "x-request"); len(got) != 1 || got[0] != "request" {
		t.Fatalf("recorded x-request = %v, want request", got)
	}
	debug := unary.JSONDebug.(map[string]any)
	requestDebug := debug["request"].(map[string]any)
	payloadDebug := requestDebug["payload"].(map[string]any)
	if got := payloadDebug["body"]; got != "[FILTERED]" {
		t.Fatalf("recorded debug payload body = %v, want [FILTERED]", got)
	}
	serverStreamRequest := cassette.GRPCInteractions[2].Request.Body.Content.([]byte)
	if len(serverStreamRequest) != 0 {
		t.Fatalf("server-streaming request uses chunk framing: %x", serverStreamRequest)
	}
	clientStreamResponse := cassette.GRPCInteractions[3].Response.Body.Content.([]byte)
	expectedClientStreamResponse, err := proto.Marshal(
		&grpc_testing.StreamingInputCallResponse{AggregatedPayloadSize: 6},
	)
	if err != nil {
		t.Fatalf("marshal expected client-streaming response: %v", err)
	}
	if !bytes.Equal(clientStreamResponse, expectedClientStreamResponse) {
		t.Fatalf("client-streaming response = %x, want %x", clientStreamResponse, expectedClientStreamResponse)
	}

	replayer := cassetter.NewGRPCRecorder(
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
	)
	replayConnection := newGRPCClientConnection(t, "passthrough:///offline", failingGRPCDialer, replayer)
	replayClient := grpc_testing.NewTestServiceClient(replayConnection)
	exerciseGRPCClient(t, replayClient)
	response, err := replayClient.UnaryCall(context.Background(), unaryRequest())
	if err != nil {
		t.Fatalf("repeat replay unary call: %v", err)
	}
	if got := string(response.GetPayload().GetBody()); got != "unary" {
		t.Fatalf("repeat replay payload = %q, want unary", got)
	}
	if err := replayer.Close(); err != nil {
		t.Fatalf("close replay transport: %v", err)
	}
}

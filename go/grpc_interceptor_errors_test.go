package cassetter_test

import (
	"context"
	"errors"
	"path/filepath"
	"testing"

	"github.com/Kludex/cassetter/go"
	"google.golang.org/grpc/codes"
	grpc_testing "google.golang.org/grpc/interop/grpc_testing"
)

func TestGRPCInterceptorsReportNoMatchAndClosedRecorder(t *testing.T) {
	t.Parallel()
	recorder := cassetter.NewGRPCRecorder(
		cassetter.WithPath(filepath.Join(t.TempDir(), "missing.yaml")),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
	)
	connection := newGRPCClientConnection(t, "passthrough:///offline", failingGRPCDialer, recorder)
	client := grpc_testing.NewTestServiceClient(connection)
	_, err := client.EmptyCall(context.Background(), &grpc_testing.Empty{})
	if !errors.Is(err, cassetter.ErrNoMatch) {
		t.Fatalf("missing interaction error = %v, want ErrNoMatch", err)
	}
	var noMatch *cassetter.NoGRPCMatchError
	if !errors.As(err, &noMatch) || noMatch.Method != grpc_testing.TestService_EmptyCall_FullMethodName {
		t.Fatalf("missing interaction error = %v, want typed gRPC method", err)
	}
	if err := recorder.Close(); err != nil {
		t.Fatalf("close recorder: %v", err)
	}
	_, err = client.EmptyCall(context.Background(), &grpc_testing.Empty{})
	if !errors.Is(err, cassetter.ErrTransportClosed) {
		t.Fatalf("closed recorder error = %v, want ErrTransportClosed", err)
	}
}

func TestGRPCRecorderReportsIncompleteStream(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "incomplete.yaml")
	target, dialer := startGRPCTestServer(t)
	recorder := cassetter.NewGRPCRecorder(
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeAll),
	)
	connection := newGRPCClientConnection(t, target, dialer, recorder)
	client := grpc_testing.NewTestServiceClient(connection)
	if _, err := client.FullDuplexCall(context.Background()); err != nil {
		t.Fatalf("create bidi stream: %v", err)
	}
	err := recorder.Close()
	if !errors.Is(err, cassetter.ErrIncompleteRecording) {
		t.Fatalf("close recorder error = %v, want ErrIncompleteRecording", err)
	}
	var incomplete *cassetter.IncompleteGRPCRecordingError
	if !errors.As(err, &incomplete) || incomplete.Method != grpc_testing.TestService_FullDuplexCall_FullMethodName {
		t.Fatalf("close recorder error = %v, want typed gRPC method", err)
	}
}

func TestGRPCInterceptorsRejectMalformedRecordedBodies(t *testing.T) {
	t.Parallel()
	tests := map[string]struct {
		method   string
		response cassetter.GRPCResponse
		invoke   func(grpc_testing.TestServiceClient) error
	}{
		"unary body type": {
			method: grpc_testing.TestService_EmptyCall_FullMethodName,
			response: cassetter.GRPCResponse{
				StatusCode:    uint32(codes.OK),
				StatusMessage: "OK",
				Body:          cassetter.Body{Type: cassetter.BodyTypeText, Content: "invalid"},
			},
			invoke: func(client grpc_testing.TestServiceClient) error {
				_, err := client.EmptyCall(context.Background(), &grpc_testing.Empty{})
				return err
			},
		},
		"stream chunks": {
			method: grpc_testing.TestService_StreamingOutputCall_FullMethodName,
			response: cassetter.GRPCResponse{
				StatusCode:    uint32(codes.OK),
				StatusMessage: "OK",
				Body:          cassetter.Body{Type: cassetter.BodyTypeBinary, Content: []byte{0, 0}},
			},
			invoke: func(client grpc_testing.TestServiceClient) error {
				_, err := client.StreamingOutputCall(context.Background(), &grpc_testing.StreamingOutputCallRequest{})
				return err
			},
		},
	}
	for name, test := range tests {
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			path := filepath.Join(t.TempDir(), "malformed.yaml")
			cassette := &cassetter.Cassette{
				Version:      1,
				Interactions: []cassetter.HTTPInteraction{},
				GRPCInteractions: []cassetter.GRPCInteraction{{
					Request:  cassetter.GRPCRequest{Method: test.method, Body: cassetter.Body{Type: cassetter.BodyTypeNone}},
					Response: test.response,
				}},
			}
			if err := cassette.Save(path); err != nil {
				t.Fatalf("save malformed cassette: %v", err)
			}
			recorder := cassetter.NewTestGRPCRecorder(
				t,
				cassetter.WithPath(path),
				cassetter.WithRecordMode(cassetter.RecordModeNone),
			)
			connection := newGRPCClientConnection(t, "passthrough:///offline", failingGRPCDialer, recorder)
			if err := test.invoke(grpc_testing.NewTestServiceClient(connection)); err == nil {
				t.Fatal("malformed recorded body returned no error")
			}
		})
	}
}

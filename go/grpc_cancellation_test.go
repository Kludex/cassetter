package cassetter_test

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/Kludex/cassetter/go"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	grpc_testing "google.golang.org/grpc/interop/grpc_testing"
	"google.golang.org/grpc/status"
)

func TestGRPCReplayHonorsCancellationAndOnFinish(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "canceled.yaml")
	cassette := &cassetter.Cassette{
		Version:      1,
		Interactions: []cassetter.HTTPInteraction{},
		GRPCInteractions: []cassetter.GRPCInteraction{
			{
				Request: cassetter.GRPCRequest{Method: grpc_testing.TestService_EmptyCall_FullMethodName},
				Response: cassetter.GRPCResponse{
					StatusMessage: "OK",
					Body:          cassetter.Body{Type: cassetter.BodyTypeBinary, Content: []byte{}},
				},
			},
			{
				Request: cassetter.GRPCRequest{Method: grpc_testing.TestService_StreamingOutputCall_FullMethodName},
				Response: cassetter.GRPCResponse{
					StatusMessage: "OK",
					Body: cassetter.Body{
						Type:    cassetter.BodyTypeBinary,
						Content: []byte{0, 0, 0, 0, 0, 0, 0, 0},
					},
				},
			},
		},
	}
	if err := cassette.Save(path); err != nil {
		t.Fatalf("save cassette: %v", err)
	}
	recorder := cassetter.NewTestGRPCRecorder(
		t,
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeNone),
	)
	connection := newGRPCClientConnection(t, "passthrough:///offline", failingGRPCDialer, recorder)
	client := grpc_testing.NewTestServiceClient(connection)

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	unaryFinished := make(chan error, 1)
	_, err := client.EmptyCall(ctx, &grpc_testing.Empty{}, grpc.OnFinish(func(err error) { unaryFinished <- err }))
	if status.Code(err) != codes.Canceled {
		t.Fatalf("canceled unary call = %v, want canceled", err)
	}
	if finishErr := <-unaryFinished; status.Code(finishErr) != codes.Canceled {
		t.Fatalf("canceled unary OnFinish = %v, want canceled", finishErr)
	}

	streamCtx, cancelStream := context.WithCancel(context.Background())
	streamFinished := make(chan error, 1)
	stream, err := client.StreamingOutputCall(
		streamCtx,
		&grpc_testing.StreamingOutputCallRequest{},
		grpc.OnFinish(func(err error) { streamFinished <- err }),
	)
	if err != nil {
		t.Fatalf("create replay stream: %v", err)
	}
	if _, err := stream.Recv(); err != nil {
		t.Fatalf("receive first replay chunk: %v", err)
	}
	cancelStream()
	if _, err := stream.Recv(); status.Code(err) != codes.Canceled {
		t.Fatalf("receive canceled replay stream = %v, want canceled", err)
	}
	select {
	case finishErr := <-streamFinished:
		if status.Code(finishErr) != codes.Canceled {
			t.Fatalf("canceled stream OnFinish = %v, want canceled", finishErr)
		}
	case <-time.After(time.Second):
		t.Fatal("canceled stream did not invoke OnFinish")
	}
}

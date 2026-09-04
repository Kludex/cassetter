package cassetter_test

import (
	"context"
	"io"
	"path/filepath"
	"testing"

	"github.com/Kludex/cassetter/go"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/emptypb"
)

type failedSendClientStream struct {
	ctx context.Context
}

func (s *failedSendClientStream) Header() (metadata.MD, error) {
	return nil, nil
}

func (s *failedSendClientStream) Trailer() metadata.MD {
	return nil
}

func (s *failedSendClientStream) CloseSend() error {
	return nil
}

func (s *failedSendClientStream) Context() context.Context {
	return s.ctx
}

func (s *failedSendClientStream) SendMsg(any) error {
	return status.Error(codes.Aborted, "send failed")
}

func (s *failedSendClientStream) RecvMsg(any) error {
	return io.EOF
}

func TestGRPCRecorderFinalizesTerminalSendError(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "send-error.yaml")
	recorder := cassetter.NewGRPCRecorder(
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeAll),
	)
	interceptor := recorder.StreamClientInterceptor()
	ctx := context.Background()
	stream, err := interceptor(
		ctx,
		&grpc.StreamDesc{ClientStreams: true, ServerStreams: true},
		nil,
		"/test.Service/Stream",
		func(context.Context, *grpc.StreamDesc, *grpc.ClientConn, string, ...grpc.CallOption) (grpc.ClientStream, error) {
			return &failedSendClientStream{ctx: ctx}, nil
		},
	)
	if err != nil {
		t.Fatalf("create stream: %v", err)
	}
	if err := stream.SendMsg(&emptypb.Empty{}); status.Code(err) != codes.Aborted {
		t.Fatalf("send error = %v, want aborted", err)
	}
	if err := recorder.Close(); err != nil {
		t.Fatalf("close recorder: %v", err)
	}
	cassette, err := cassetter.Load(path)
	if err != nil {
		t.Fatalf("load cassette: %v", err)
	}
	response := cassette.GRPCInteractions[0].Response
	if response.StatusCode != uint32(codes.Aborted) || response.StatusMessage != "send failed" {
		t.Fatalf("recorded status = %d %q, want aborted", response.StatusCode, response.StatusMessage)
	}
}

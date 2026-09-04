package cassetter

import (
	"context"
	"io"
	"sync"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

type replayGRPCClientStream struct {
	ctx           context.Context
	metadata      metadata.MD
	chunks        [][]byte
	statusCode    codes.Code
	statusMessage string
	mu            sync.Mutex
	next          int
}

func newReplayGRPCStream(
	ctx context.Context,
	description *grpc.StreamDesc,
	response GRPCResponse,
	options []grpc.CallOption,
) (grpc.ClientStream, error) {
	content, err := grpcBodyBytes(response.Body)
	if err != nil {
		return nil, err
	}
	var chunks [][]byte
	if description.ServerStreams {
		chunks, err = decodeGRPCChunks(content)
		if err != nil {
			return nil, err
		}
	} else if response.StatusCode == uint32(codes.OK) {
		chunks = [][]byte{content}
	}
	applyGRPCCallMetadata(options, response.Metadata)
	return &replayGRPCClientStream{
		ctx:           ctx,
		metadata:      replayGRPCMetadata(response.Metadata),
		chunks:        chunks,
		statusCode:    codes.Code(response.StatusCode),
		statusMessage: response.StatusMessage,
	}, nil
}

func (s *replayGRPCClientStream) Header() (metadata.MD, error) {
	return s.metadata.Copy(), nil
}

func (s *replayGRPCClientStream) Trailer() metadata.MD {
	return s.metadata.Copy()
}

func (s *replayGRPCClientStream) CloseSend() error {
	return nil
}

func (s *replayGRPCClientStream) Context() context.Context {
	return s.ctx
}

func (s *replayGRPCClientStream) SendMsg(message any) error {
	_, err := marshalGRPCMessage(message)
	return err
}

func (s *replayGRPCClientStream) RecvMsg(message any) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.next < len(s.chunks) {
		content := s.chunks[s.next]
		s.next++
		return unmarshalGRPCMessage(content, message)
	}
	if s.statusCode != codes.OK {
		return status.Error(s.statusCode, s.statusMessage)
	}
	return io.EOF
}

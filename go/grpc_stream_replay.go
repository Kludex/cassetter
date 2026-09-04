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
	serverStreams bool
	options       []grpc.CallOption
	mu            sync.Mutex
	next          int
	finishMu      sync.Mutex
	didFinish     bool
	finished      chan struct{}
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
	stream := &replayGRPCClientStream{
		ctx:           ctx,
		metadata:      replayGRPCMetadata(response.Metadata),
		chunks:        chunks,
		statusCode:    codes.Code(response.StatusCode),
		statusMessage: response.StatusMessage,
		serverStreams: description.ServerStreams,
		options:       append([]grpc.CallOption(nil), options...),
		finished:      make(chan struct{}),
	}
	if done := ctx.Done(); done != nil {
		go func() {
			select {
			case <-done:
				stream.finish(grpcContextError(ctx))
			case <-stream.finished:
			}
		}()
	}
	return stream, nil
}

func (s *replayGRPCClientStream) Header() (metadata.MD, error) {
	if err := grpcContextError(s.ctx); err != nil {
		s.finish(err)
		return nil, err
	}
	return s.metadata.Copy(), nil
}

func (s *replayGRPCClientStream) Trailer() metadata.MD {
	return s.metadata.Copy()
}

func (s *replayGRPCClientStream) CloseSend() error {
	if err := grpcContextError(s.ctx); err != nil {
		s.finish(err)
		return err
	}
	return nil
}

func (s *replayGRPCClientStream) Context() context.Context {
	return s.ctx
}

func (s *replayGRPCClientStream) SendMsg(message any) error {
	if err := grpcContextError(s.ctx); err != nil {
		s.finish(err)
		return err
	}
	_, err := marshalGRPCMessage(message)
	if err != nil {
		s.finish(err)
	}
	return err
}

func (s *replayGRPCClientStream) RecvMsg(message any) error {
	if err := grpcContextError(s.ctx); err != nil {
		s.finish(err)
		return err
	}
	s.mu.Lock()
	if err := grpcContextError(s.ctx); err != nil {
		s.mu.Unlock()
		s.finish(err)
		return err
	}
	if s.next < len(s.chunks) {
		content := s.chunks[s.next]
		s.next++
		serverStreams := s.serverStreams
		s.mu.Unlock()
		if err := unmarshalGRPCMessage(content, message); err != nil {
			s.finish(err)
			return err
		}
		if !serverStreams {
			s.finish(nil)
		}
		return nil
	}
	statusCode := s.statusCode
	statusMessage := s.statusMessage
	s.mu.Unlock()
	if statusCode != codes.OK {
		err := status.Error(statusCode, statusMessage)
		s.finish(err)
		return err
	}
	s.finish(nil)
	return io.EOF
}

func (s *replayGRPCClientStream) finish(err error) {
	s.finishMu.Lock()
	if s.didFinish {
		s.finishMu.Unlock()
		return
	}
	s.didFinish = true
	close(s.finished)
	s.finishMu.Unlock()
	finishGRPCCallOptions(s.options, err)
}

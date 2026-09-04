package cassetter

import (
	"context"
	"errors"
	"io"
	"sync"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"
)

type recordingGRPCClientStream struct {
	grpc.ClientStream
	transport   *Transport
	description *grpc.StreamDesc
	ctx         context.Context
	method      string
	order       uint64

	requestMu      sync.Mutex
	requestChunks  [][]byte
	responseMu     sync.Mutex
	responseChunks [][]byte
	finishOnce     sync.Once
	finishErr      error
}

func (s *recordingGRPCClientStream) SendMsg(message any) error {
	content, err := marshalGRPCMessage(message)
	if err != nil {
		return s.failRecording(err)
	}
	s.requestMu.Lock()
	defer s.requestMu.Unlock()
	if err := s.ClientStream.SendMsg(message); err != nil {
		return err
	}
	s.requestChunks = append(s.requestChunks, content)
	return nil
}

func (s *recordingGRPCClientStream) RecvMsg(message any) error {
	err := s.ClientStream.RecvMsg(message)
	if err != nil {
		terminalError := err
		if errors.Is(err, io.EOF) {
			terminalError = nil
		}
		return joinGRPCErrors(err, s.finalize(terminalError))
	}
	content, err := marshalGRPCMessage(message)
	if err != nil {
		return s.failRecording(err)
	}
	s.responseMu.Lock()
	s.responseChunks = append(s.responseChunks, content)
	s.responseMu.Unlock()
	if !s.description.ServerStreams {
		return s.finalize(nil)
	}
	return nil
}

func (s *recordingGRPCClientStream) finalize(terminalError error) error {
	s.finishOnce.Do(func() {
		headerMetadata, _ := s.Header()
		trailerMetadata := s.Trailer()
		s.requestMu.Lock()
		requestChunks := append([][]byte(nil), s.requestChunks...)
		s.requestMu.Unlock()
		s.responseMu.Lock()
		responseChunks := append([][]byte(nil), s.responseChunks...)
		s.responseMu.Unlock()
		statusCode, statusMessage := grpcStreamStatus(terminalError)
		outgoingMetadata, _ := metadata.FromOutgoingContext(s.ctx)
		interaction := GRPCInteraction{
			Request: GRPCRequest{
				Method:   s.method,
				Metadata: grpcMetadataHeader(outgoingMetadata),
				Body:     Body{Type: BodyTypeBinary, Content: encodeGRPCChunks(requestChunks)},
			},
			Response: GRPCResponse{
				StatusCode:    uint32(statusCode),
				StatusMessage: statusMessage,
				Metadata:      mergeGRPCMetadata(headerMetadata, trailerMetadata),
				Body:          Body{Type: BodyTypeBinary, Content: encodeGRPCChunks(responseChunks)},
			},
			RecordedAt: time.Now().UTC().Format(time.RFC3339Nano),
		}
		s.finishErr = s.transport.recordGRPC(interaction, s.order)
	})
	return s.finishErr
}

func (s *recordingGRPCClientStream) failRecording(err error) error {
	s.finishOnce.Do(func() {
		s.finishErr = err
		s.transport.finishGRPCRecording(s.order, err)
	})
	return err
}

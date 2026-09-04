package cassetter

import (
	"context"
	"fmt"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

// UnaryClientInterceptor returns a gRPC unary client interceptor backed by the cassette.
func (t *Transport) UnaryClientInterceptor() grpc.UnaryClientInterceptor {
	return func(
		ctx context.Context,
		method string,
		request any,
		reply any,
		connection *grpc.ClientConn,
		invoker grpc.UnaryInvoker,
		options ...grpc.CallOption,
	) error {
		return t.interceptUnaryGRPC(ctx, method, request, reply, connection, invoker, options...)
	}
}

func (t *Transport) interceptUnaryGRPC(
	ctx context.Context,
	method string,
	request any,
	reply any,
	connection *grpc.ClientConn,
	invoker grpc.UnaryInvoker,
	options ...grpc.CallOption,
) error {
	if err := t.Initialize(); err != nil {
		return err
	}
	if err := t.checkOpen(); err != nil {
		return err
	}
	requestContent, err := marshalGRPCMessage(request)
	if err != nil {
		return err
	}
	if t.config.mode != RecordModeAll && t.config.mode != RecordModeRewrite {
		interaction, found, err := t.takeGRPCMatch(method)
		if err != nil {
			return err
		}
		if found {
			return replayUnaryGRPC(interaction.Response, reply, options)
		}
	}
	if !t.canRecord {
		return &NoGRPCMatchError{Method: method}
	}
	order, err := t.reserveGRPCRecording(method)
	if err != nil {
		return err
	}
	var headerMetadata metadata.MD
	var trailerMetadata metadata.MD
	callOptions := append([]grpc.CallOption(nil), options...)
	callOptions = append(callOptions, grpc.Header(&headerMetadata), grpc.Trailer(&trailerMetadata))
	callErr := invoker(ctx, method, request, reply, connection, callOptions...)
	interaction, err := buildUnaryGRPCInteraction(
		ctx,
		method,
		request,
		reply,
		requestContent,
		headerMetadata,
		trailerMetadata,
		callErr,
	)
	if err != nil {
		t.finishGRPCRecording(order, err)
		return joinGRPCErrors(callErr, err)
	}
	err = t.recordGRPC(interaction, order)
	return joinGRPCErrors(callErr, err)
}

func replayUnaryGRPC(response GRPCResponse, reply any, options []grpc.CallOption) error {
	applyGRPCCallMetadata(options, response.Metadata)
	if response.StatusCode != uint32(codes.OK) {
		return status.Error(codes.Code(response.StatusCode), response.StatusMessage)
	}
	content, err := grpcBodyBytes(response.Body)
	if err != nil {
		return fmt.Errorf("replay gRPC response: %w", err)
	}
	return unmarshalGRPCMessage(content, reply)
}

func buildUnaryGRPCInteraction(
	ctx context.Context,
	method string,
	request any,
	reply any,
	requestContent []byte,
	headerMetadata metadata.MD,
	trailerMetadata metadata.MD,
	callErr error,
) (GRPCInteraction, error) {
	responseContent, err := marshalGRPCMessage(reply)
	if err != nil {
		return GRPCInteraction{}, err
	}
	requestDebug, err := grpcJSONValue(request)
	if err != nil {
		return GRPCInteraction{}, err
	}
	responseDebug, err := grpcJSONValue(reply)
	if err != nil {
		return GRPCInteraction{}, err
	}
	statusCode := codes.OK
	statusMessage := "OK"
	if callErr != nil {
		statusValue := status.Convert(callErr)
		statusCode = statusValue.Code()
		statusMessage = statusValue.Message()
	}
	outgoingMetadata, _ := metadata.FromOutgoingContext(ctx)
	return GRPCInteraction{
		Request: GRPCRequest{
			Method:   method,
			Metadata: grpcMetadataHeader(outgoingMetadata),
			Body:     Body{Type: BodyTypeBinary, Content: requestContent},
		},
		Response: GRPCResponse{
			StatusCode:    uint32(statusCode),
			StatusMessage: statusMessage,
			Metadata:      mergeGRPCMetadata(headerMetadata, trailerMetadata),
			Body:          Body{Type: BodyTypeBinary, Content: responseContent},
		},
		JSONDebug:  map[string]any{"request": requestDebug, "response": responseDebug},
		RecordedAt: time.Now().UTC().Format(time.RFC3339Nano),
	}, nil
}

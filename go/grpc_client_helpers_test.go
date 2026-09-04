package cassetter_test

import (
	"context"
	"errors"
	"net"
	"strings"
	"testing"

	"github.com/Kludex/cassetter/go"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	grpc_testing "google.golang.org/grpc/interop/grpc_testing"
)

func unaryRequest() *grpc_testing.SimpleRequest {
	return &grpc_testing.SimpleRequest{Payload: grpcPayload("unary"), FillOauthScope: true}
}

func newGRPCClientConnection(
	t *testing.T,
	target string,
	dialer func(context.Context, string) (net.Conn, error),
	recorder *cassetter.Transport,
) *grpc.ClientConn {
	t.Helper()
	connection, err := grpc.NewClient(
		target,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithContextDialer(dialer),
		grpc.WithChainUnaryInterceptor(recorder.UnaryClientInterceptor()),
		grpc.WithChainStreamInterceptor(recorder.StreamClientInterceptor()),
	)
	if err != nil {
		t.Fatalf("create gRPC client: %v", err)
	}
	t.Cleanup(func() {
		if err := connection.Close(); err != nil {
			t.Errorf("close gRPC connection: %v", err)
		}
	})
	return connection
}

func failingGRPCDialer(context.Context, string) (net.Conn, error) {
	return nil, errors.New("unexpected gRPC network access")
}

func grpcHeaderValues(headers map[string][]string, name string) []string {
	for candidate, values := range headers {
		if strings.EqualFold(candidate, name) {
			return values
		}
	}
	return nil
}

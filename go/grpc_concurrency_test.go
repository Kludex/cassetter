package cassetter_test

import (
	"context"
	"path/filepath"
	"testing"

	"github.com/Kludex/cassetter/go"
	"google.golang.org/grpc"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

func TestGRPCRecorderPersistsConcurrentCallsInStartOrder(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), "ordered.yaml")
	recorder := cassetter.NewGRPCRecorder(
		cassetter.WithPath(path),
		cassetter.WithRecordMode(cassetter.RecordModeAll),
	)
	interceptor := recorder.UnaryClientInterceptor()
	slowStarted := make(chan struct{})
	releaseSlow := make(chan struct{})
	slowResult := make(chan error, 1)
	go func() {
		slowResult <- interceptor(
			context.Background(),
			"/test.Service/Slow",
			wrapperspb.String("request"),
			wrapperspb.String(""),
			nil,
			func(
				context.Context,
				string,
				any,
				any,
				*grpc.ClientConn,
				...grpc.CallOption,
			) error {
				close(slowStarted)
				<-releaseSlow
				return nil
			},
		)
	}()
	<-slowStarted
	fastErr := interceptor(
		context.Background(),
		"/test.Service/Fast",
		wrapperspb.String("request"),
		wrapperspb.String(""),
		nil,
		func(context.Context, string, any, any, *grpc.ClientConn, ...grpc.CallOption) error {
			return nil
		},
	)
	if fastErr != nil {
		t.Fatalf("fast call: %v", fastErr)
	}
	close(releaseSlow)
	if err := <-slowResult; err != nil {
		t.Fatalf("slow call: %v", err)
	}
	if err := recorder.Close(); err != nil {
		t.Fatalf("close recorder: %v", err)
	}
	cassette, err := cassetter.Load(path)
	if err != nil {
		t.Fatalf("load cassette: %v", err)
	}
	methods := []string{
		cassette.GRPCInteractions[0].Request.Method,
		cassette.GRPCInteractions[1].Request.Method,
	}
	if methods[0] != "/test.Service/Slow" || methods[1] != "/test.Service/Fast" {
		t.Fatalf("recorded methods = %v, want start order", methods)
	}
}

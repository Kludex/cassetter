package cassetter

import (
	"net/http"
	"strings"

	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"
)

func grpcMetadataHeader(values metadata.MD) http.Header {
	headers := make(http.Header, len(values))
	for name, entries := range values {
		for _, entry := range entries {
			headers[strings.ToLower(name)] = append(headers[strings.ToLower(name)], strings.ToValidUTF8(entry, "�"))
		}
	}
	return headers
}

func mergeGRPCMetadata(values ...metadata.MD) http.Header {
	merged := metadata.MD{}
	for _, value := range values {
		for name, entries := range value {
			merged[name] = append(merged[name], entries...)
		}
	}
	return grpcMetadataHeader(merged)
}

func replayGRPCMetadata(headers http.Header) metadata.MD {
	values := make(metadata.MD, len(headers))
	for name, entries := range headers {
		values[strings.ToLower(name)] = append([]string(nil), entries...)
	}
	return values
}

func applyGRPCCallMetadata(options []grpc.CallOption, headers http.Header) {
	values := replayGRPCMetadata(headers)
	for _, option := range options {
		switch typed := option.(type) {
		case grpc.HeaderCallOption:
			if typed.HeaderAddr != nil {
				*typed.HeaderAddr = values.Copy()
			}
		case *grpc.HeaderCallOption:
			if typed != nil && typed.HeaderAddr != nil {
				*typed.HeaderAddr = values.Copy()
			}
		case grpc.TrailerCallOption:
			if typed.TrailerAddr != nil {
				*typed.TrailerAddr = values.Copy()
			}
		case *grpc.TrailerCallOption:
			if typed != nil && typed.TrailerAddr != nil {
				*typed.TrailerAddr = values.Copy()
			}
		}
	}
}

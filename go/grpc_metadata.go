package cassetter

import (
	"encoding/base64"
	"net/http"
	"strings"

	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"
)

func grpcMetadataHeader(values metadata.MD) http.Header {
	headers := make(http.Header, len(values))
	for name, entries := range values {
		name = strings.ToLower(name)
		for _, entry := range entries {
			if strings.HasSuffix(name, "-bin") {
				entry = base64.StdEncoding.EncodeToString([]byte(entry))
			} else {
				entry = strings.ToValidUTF8(entry, "�")
			}
			headers[name] = append(headers[name], entry)
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
		name = strings.ToLower(name)
		for _, entry := range entries {
			if strings.HasSuffix(name, "-bin") {
				if decoded, err := base64.StdEncoding.DecodeString(entry); err == nil {
					entry = string(decoded)
				} else if decoded, err := base64.RawStdEncoding.DecodeString(entry); err == nil {
					entry = string(decoded)
				}
			}
			values[name] = append(values[name], entry)
		}
	}
	return values
}

func finishGRPCCallOptions(options []grpc.CallOption, callErr error) {
	for _, option := range options {
		switch typed := option.(type) {
		case grpc.OnFinishCallOption:
			if typed.OnFinish != nil {
				typed.OnFinish(callErr)
			}
		case *grpc.OnFinishCallOption:
			if typed != nil && typed.OnFinish != nil {
				typed.OnFinish(callErr)
			}
		}
	}
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

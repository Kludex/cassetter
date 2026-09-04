package cassetter

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"

	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/protoadapt"
)

func marshalGRPCMessage(message any) ([]byte, error) {
	protobuf, ok := grpcProtoMessage(message)
	if !ok {
		return nil, fmt.Errorf("cassetter: gRPC message %T does not implement proto.Message", message)
	}
	content, err := (proto.MarshalOptions{Deterministic: true}).Marshal(protobuf)
	if err != nil {
		return nil, fmt.Errorf("marshal gRPC message: %w", err)
	}
	return content, nil
}

func unmarshalGRPCMessage(content []byte, message any) error {
	protobuf, ok := grpcProtoMessage(message)
	if !ok {
		return fmt.Errorf("cassetter: gRPC message %T does not implement proto.Message", message)
	}
	if err := proto.Unmarshal(content, protobuf); err != nil {
		return fmt.Errorf("unmarshal recorded gRPC message: %w", err)
	}
	return nil
}

func grpcBodyBytes(body Body) ([]byte, error) {
	if body.Type == "" || body.Type == BodyTypeNone {
		return nil, nil
	}
	if body.Type != BodyTypeBinary {
		return nil, fmt.Errorf("recorded gRPC body has type %q, want %q", body.Type, BodyTypeBinary)
	}
	content, ok := body.Content.([]byte)
	if !ok {
		return nil, errors.New("recorded gRPC binary body content must be []byte")
	}
	return content, nil
}

func grpcJSONValue(message any) (any, error) {
	protobuf, ok := grpcProtoMessage(message)
	if !ok {
		return nil, fmt.Errorf("cassetter: gRPC message %T does not implement proto.Message", message)
	}
	content, err := (protojson.MarshalOptions{UseProtoNames: true}).Marshal(protobuf)
	if err != nil {
		return nil, fmt.Errorf("marshal gRPC debug JSON: %w", err)
	}
	decoder := json.NewDecoder(bytes.NewReader(content))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		return nil, fmt.Errorf("decode gRPC debug JSON: %w", err)
	}
	return value, nil
}

func grpcProtoMessage(message any) (proto.Message, bool) {
	switch typed := message.(type) {
	case protoadapt.MessageV1:
		return protoadapt.MessageV2Of(typed), true
	case protoadapt.MessageV2:
		return typed, true
	default:
		return nil, false
	}
}

func encodeGRPCChunks(chunks [][]byte) []byte {
	var output bytes.Buffer
	for _, chunk := range chunks {
		_ = binary.Write(&output, binary.BigEndian, uint32(len(chunk)))
		_, _ = output.Write(chunk)
	}
	return output.Bytes()
}

func decodeGRPCChunks(content []byte) ([][]byte, error) {
	reader := bytes.NewReader(content)
	chunks := make([][]byte, 0)
	for reader.Len() > 0 {
		var size uint32
		if err := binary.Read(reader, binary.BigEndian, &size); err != nil {
			return nil, fmt.Errorf("decode recorded gRPC stream: %w", err)
		}
		if uint64(size) > uint64(reader.Len()) {
			return nil, io.ErrUnexpectedEOF
		}
		chunk := make([]byte, size)
		if _, err := io.ReadFull(reader, chunk); err != nil {
			return nil, fmt.Errorf("decode recorded gRPC stream: %w", err)
		}
		chunks = append(chunks, chunk)
	}
	return chunks, nil
}

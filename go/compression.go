package cassetter

import (
	"bytes"
	"compress/flate"
	"compress/gzip"
	"compress/zlib"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"

	"github.com/andybalholm/brotli"
	"github.com/klauspost/compress/zstd"
)

const maxDecompressedBody = 256 * 1024 * 1024

func decodeBody(content []byte, headers http.Header) ([]byte, error) {
	var encodings []string
	for name, values := range headers {
		if !strings.EqualFold(name, "content-encoding") {
			continue
		}
		for _, value := range values {
			for encoding := range strings.SplitSeq(value, ",") {
				encodings = append(encodings, strings.ToLower(strings.TrimSpace(encoding)))
			}
		}
	}
	if len(encodings) == 0 {
		return content, nil
	}
	decoded := content
	for index := len(encodings) - 1; index >= 0; index-- {
		var err error
		decoded, err = decodeEncoding(decoded, encodings[index])
		if err != nil {
			return nil, fmt.Errorf("decode %s body: %w", encodings[index], err)
		}
	}
	removeHeader(headers, "content-encoding")
	if len(decoded) > 0 {
		for name := range headers {
			if strings.EqualFold(name, "content-length") {
				headers[name] = []string{strconv.Itoa(len(decoded))}
			}
		}
	}
	return decoded, nil
}

func decodeEncoding(content []byte, encoding string) ([]byte, error) {
	switch encoding {
	case "", "identity":
		return content, nil
	case "gzip", "x-gzip":
		reader, err := gzip.NewReader(bytes.NewReader(content))
		if err != nil {
			return nil, err
		}
		defer func() {
			_ = reader.Close()
		}()
		return readCapped(reader)
	case "deflate":
		reader, err := zlib.NewReader(bytes.NewReader(content))
		if err == nil {
			defer func() {
				_ = reader.Close()
			}()
			return readCapped(reader)
		}
		raw := flate.NewReader(bytes.NewReader(content))
		defer func() {
			_ = raw.Close()
		}()
		return readCapped(raw)
	case "br":
		return readCapped(brotli.NewReader(bytes.NewReader(content)))
	case "zstd":
		reader, err := zstd.NewReader(bytes.NewReader(content))
		if err != nil {
			return nil, err
		}
		defer reader.Close()
		return readCapped(reader)
	default:
		return nil, fmt.Errorf("unsupported content encoding %q", encoding)
	}
}

func readCapped(reader io.Reader) ([]byte, error) {
	content, err := io.ReadAll(io.LimitReader(reader, maxDecompressedBody+1))
	if err != nil {
		return nil, err
	}
	if len(content) > maxDecompressedBody {
		return nil, fmt.Errorf("body exceeds the %d byte decompression limit", maxDecompressedBody)
	}
	return content, nil
}

func removeHeader(headers http.Header, target string) {
	for name := range headers {
		if strings.EqualFold(name, target) {
			delete(headers, name)
		}
	}
}

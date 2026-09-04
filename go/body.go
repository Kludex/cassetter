package cassetter

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"mime"
	"net/http"
	"strconv"
	"strings"
	"unicode/utf8"

	"golang.org/x/text/unicode/norm"
)

func bodyFromBytes(content []byte, contentType string) Body {
	if len(content) == 0 {
		return Body{Type: BodyTypeNone}
	}
	validText := utf8.Valid(content)
	if validText {
		content = []byte(norm.NFC.String(string(content)))
	}
	mediaType, _, _ := mime.ParseMediaType(contentType)
	if mediaType == "application/json" || strings.HasSuffix(mediaType, "+json") || contentType == "" {
		var value any
		decoder := json.NewDecoder(bytes.NewReader(content))
		decoder.UseNumber()
		if decoder.Decode(&value) == nil {
			var extra any
			if decoder.Decode(&extra) == io.EOF {
				content := normalizeJSONUnicode(materializeJSONNumbers(value))
				return Body{Type: BodyTypeJSON, Content: content}
			}
		}
	}
	if validText {
		return Body{Type: BodyTypeText, Content: string(content)}
	}
	return Body{Type: BodyTypeBinary, Content: bytes.Clone(content)}
}

func bodyBytes(body Body) ([]byte, error) {
	switch body.Type {
	case BodyTypeNone, "":
		return nil, nil
	case BodyTypeJSON:
		content, err := json.Marshal(body.Content)
		if err != nil {
			return nil, fmt.Errorf("encode JSON body: %w", err)
		}
		return content, nil
	case BodyTypeText:
		content, ok := body.Content.(string)
		if !ok {
			return nil, fmt.Errorf("text body content must be a string")
		}
		return []byte(content), nil
	case BodyTypeBinary:
		content, ok := body.Content.([]byte)
		if !ok {
			return nil, fmt.Errorf("binary body content must be []byte")
		}
		return bytes.Clone(content), nil
	default:
		return nil, fmt.Errorf("unknown body type %q", body.Type)
	}
}

func retagContentLength(headers http.Header, body Body) {
	content, err := bodyBytes(body)
	if err != nil || len(content) == 0 {
		return
	}
	for name := range headers {
		if strings.EqualFold(name, "content-length") {
			headers[name] = []string{strconv.Itoa(len(content))}
		}
	}
}

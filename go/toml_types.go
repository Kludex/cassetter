package cassetter

import "net/http"

type tomlCassette struct {
	Version      int               `toml:"version"`
	Interactions []tomlInteraction `toml:"interactions"`
}

type tomlInteraction struct {
	Request    tomlRequest  `toml:"request"`
	Response   tomlResponse `toml:"response"`
	RecordedAt string       `toml:"recorded_at,omitempty"`
}

type tomlRequest struct {
	Method      string      `toml:"method"`
	URI         string      `toml:"uri"`
	Headers     http.Header `toml:"headers"`
	BodyType    BodyType    `toml:"body_type"`
	BodyContent *string     `toml:"body_content,omitempty"`
}

type tomlResponse struct {
	Status      int         `toml:"status"`
	Headers     http.Header `toml:"headers"`
	BodyType    BodyType    `toml:"body_type"`
	BodyContent *string     `toml:"body_content,omitempty"`
}

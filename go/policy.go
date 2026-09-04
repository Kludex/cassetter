package cassetter

import (
	"errors"
	"fmt"
	"net/http"
	"time"
)

// ExpiryAction controls what happens when a cassette exceeds its maximum age.
type ExpiryAction string

const (
	// ExpiryWarn logs a warning and keeps the expired cassette.
	ExpiryWarn ExpiryAction = "warn"
	// ExpiryFail rejects an expired cassette.
	ExpiryFail ExpiryAction = "fail"
	// ExpiryRerecord removes an expired cassette and starts a new recording.
	ExpiryRerecord ExpiryAction = "rerecord"
)

// ErrCassetteExpired identifies a cassette that exceeds its configured maximum age.
var ErrCassetteExpired = errors.New("cassette expired")

// ErrSkipRecording tells a request or response hook to pass live traffic through without recording it.
var ErrSkipRecording = errors.New("skip cassette recording")

// CassetteExpiredError describes an expired cassette.
type CassetteExpiredError struct {
	Path   string
	Age    time.Duration
	MaxAge time.Duration
}

// Error implements error.
func (e *CassetteExpiredError) Error() string {
	return fmt.Sprintf("%s: %q is %s old (max age %s)", ErrCassetteExpired, e.Path, e.Age, e.MaxAge)
}

// Unwrap allows errors.Is(err, ErrCassetteExpired).
func (e *CassetteExpiredError) Unwrap() error {
	return ErrCassetteExpired
}

// RequestHook can modify a request before matching or recording.
// A hook that replaces the body must close the previous body.
type RequestHook func(*http.Request) error

// ResponseHook can modify a live response before recording.
// A hook that replaces the body must close the previous body.
type ResponseHook func(*http.Response) error

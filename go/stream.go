package cassetter

import (
	"bytes"
	"errors"
	"io"
	"sync"
)

type requestBody struct {
	source io.ReadCloser
	done   chan struct{}
	once   sync.Once
	mu     sync.Mutex
	buffer bytes.Buffer
}

func newRequestBody(source io.ReadCloser) *requestBody {
	body := &requestBody{source: source, done: make(chan struct{})}
	if source == nil {
		close(body.done)
	}
	return body
}

func (b *requestBody) Read(target []byte) (int, error) {
	count, err := b.source.Read(target)
	if count > 0 {
		b.mu.Lock()
		_, _ = b.buffer.Write(target[:count])
		b.mu.Unlock()
	}
	if err != nil {
		b.signalDone()
	}
	return count, err
}

func (b *requestBody) Close() error {
	err := b.source.Close()
	b.signalDone()
	return err
}

func (b *requestBody) content() []byte {
	<-b.done
	b.mu.Lock()
	defer b.mu.Unlock()
	return bytes.Clone(b.buffer.Bytes())
}

func (b *requestBody) signalDone() {
	b.once.Do(func() {
		close(b.done)
	})
}

type recordingBody struct {
	source   io.ReadCloser
	content  bytes.Buffer
	finalize func([]byte) error
	mu       sync.Mutex

	finishOnce sync.Once
	finishErr  error
	closeOnce  sync.Once
	closeErr   error
}

func newRecordingBody(source io.ReadCloser, finalize func([]byte) error) io.ReadCloser {
	return &recordingBody{source: source, finalize: finalize}
}

func (b *recordingBody) Read(target []byte) (int, error) {
	count, err := b.source.Read(target)
	if count > 0 {
		b.mu.Lock()
		_, _ = b.content.Write(target[:count])
		b.mu.Unlock()
	}
	if errors.Is(err, io.EOF) {
		if finishErr := b.finish(); finishErr != nil {
			return count, finishErr
		}
	}
	return count, err
}

func (b *recordingBody) Close() error {
	b.closeOnce.Do(func() {
		closeErr := b.source.Close()
		b.closeErr = errors.Join(closeErr, b.finish())
	})
	return b.closeErr
}

func (b *recordingBody) finish() error {
	b.finishOnce.Do(func() {
		b.mu.Lock()
		content := bytes.Clone(b.content.Bytes())
		b.mu.Unlock()
		b.finishErr = b.finalize(content)
	})
	return b.finishErr
}

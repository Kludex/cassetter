package cassetter

import (
	"errors"
	"fmt"
	"os"
	"strings"
)

func (t *Transport) load() {
	if t.config.path == "" {
		t.initErr = errors.New("cassetter: WithPath requires a cassette path")
		return
	}
	switch t.config.mode {
	case RecordModeNone, RecordModeOnce, RecordModeNewEpisodes, RecordModeAll, RecordModeRewrite:
	default:
		t.initErr = fmt.Errorf("cassetter: unknown record mode %q", t.config.mode)
		return
	}
	if err := validateMatchers(t.config.matchers); err != nil {
		t.initErr = err
		return
	}
	if t.config.mode == RecordModeRewrite {
		if err := os.Remove(t.config.path); err != nil && !errors.Is(err, os.ErrNotExist) {
			t.initErr = fmt.Errorf("remove cassette: %w", err)
			return
		}
	}
	_, statErr := os.Stat(t.config.path)
	exists := statErr == nil
	if statErr != nil && !errors.Is(statErr, os.ErrNotExist) {
		t.initErr = fmt.Errorf("inspect cassette: %w", statErr)
		return
	}
	if exists && t.config.mode != RecordModeAll && t.config.mode != RecordModeRewrite {
		t.cassette, t.initErr = Load(t.config.path)
		if t.initErr != nil {
			return
		}
	} else {
		t.cassette = &Cassette{Version: 1, Interactions: []HTTPInteraction{}}
	}
	t.played = make([]bool, len(t.cassette.Interactions))
	t.orders = make([]uint64, len(t.cassette.Interactions))
	t.index = make(map[string][]int, len(t.cassette.Interactions))
	t.pending = make(map[uint64]pendingRecording)
	for index, interaction := range t.cassette.Interactions {
		t.orders[index] = uint64(index)
		if t.usesMethodURIIndex() {
			request := t.matchingRequest(interaction.Request)
			key := matchKey(request.Method, request.URI)
			t.index[key] = append(t.index[key], index)
		}
	}
	t.nextOrder = uint64(len(t.cassette.Interactions))
	t.canRecord = t.config.mode == RecordModeNewEpisodes || t.config.mode == RecordModeAll ||
		t.config.mode == RecordModeRewrite || t.config.mode == RecordModeOnce && !exists
}

func (t *Transport) takeMatch(request HTTPRequest) (HTTPInteraction, bool, error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.closed {
		return HTTPInteraction{}, false, ErrTransportClosed
	}
	candidates := make([]int, len(t.cassette.Interactions))
	for index := range candidates {
		candidates[index] = index
	}
	if t.usesMethodURIIndex() {
		candidates = t.index[matchKey(request.Method, request.URI)]
	}
	fallback := -1
	for _, candidate := range candidates {
		if !matchesRequest(request, t.matchingRequest(t.cassette.Interactions[candidate].Request), t.config) {
			continue
		}
		if !t.played[candidate] {
			t.played[candidate] = true
			return t.cassette.Interactions[candidate], true, nil
		}
		if fallback < 0 {
			fallback = candidate
		}
	}
	if fallback >= 0 {
		return t.cassette.Interactions[fallback], true, nil
	}
	return HTTPInteraction{}, false, nil
}

func (t *Transport) reserveRecording(method string, uri string) (uint64, error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.closed {
		return 0, ErrTransportClosed
	}
	order := t.nextOrder
	t.nextOrder++
	t.pending[order] = pendingRecording{method: method, uri: uri}
	return order, nil
}

func (t *Transport) finishRecording(order uint64, err error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	delete(t.pending, order)
	if err != nil {
		t.recordErr = errors.Join(t.recordErr, err)
	}
}

func matchKey(method string, uri string) string {
	return strings.ToUpper(method) + " " + uri
}

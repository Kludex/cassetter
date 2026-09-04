package cassetter

import (
	"errors"
	"fmt"
	"os"
	"sort"
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
		key := matchKey(interaction.Request.Method, interaction.Request.URI)
		t.index[key] = append(t.index[key], index)
	}
	t.nextOrder = uint64(len(t.cassette.Interactions))
	t.canRecord = t.config.mode == RecordModeNewEpisodes || t.config.mode == RecordModeAll ||
		t.config.mode == RecordModeRewrite || t.config.mode == RecordModeOnce && !exists
}

func (t *Transport) takeMatch(method string, uri string) (HTTPInteraction, bool, error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.closed {
		return HTTPInteraction{}, false, ErrTransportClosed
	}
	for _, candidate := range t.index[matchKey(method, uri)] {
		if !t.played[candidate] {
			t.played[candidate] = true
			return t.cassette.Interactions[candidate], true, nil
		}
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

func (t *Transport) record(interaction HTTPInteraction, order uint64) error {
	cassette := &Cassette{Version: 1, Interactions: []HTTPInteraction{interaction}}
	cassette.Scrub(t.config.security)
	interaction = cassette.Interactions[0]

	t.mu.Lock()
	defer t.mu.Unlock()
	if t.closed {
		return ErrTransportClosed
	}
	candidateInteractions := append([]HTTPInteraction(nil), t.cassette.Interactions...)
	candidateInteractions = append(candidateInteractions, interaction)
	candidateOrders := append([]uint64(nil), t.orders...)
	candidateOrders = append(candidateOrders, order)

	indices := make([]int, len(candidateInteractions))
	for index := range indices {
		indices[index] = index
	}
	sort.SliceStable(indices, func(left int, right int) bool {
		return candidateOrders[indices[left]] < candidateOrders[indices[right]]
	})
	output := *t.cassette
	output.Interactions = make([]HTTPInteraction, 0, len(indices))
	for _, index := range indices {
		output.Interactions = append(output.Interactions, candidateInteractions[index])
	}
	if err := output.Save(t.config.path); err != nil {
		return err
	}

	index := len(t.cassette.Interactions)
	t.cassette.Interactions = candidateInteractions
	t.played = append(t.played, false)
	t.orders = candidateOrders
	key := matchKey(interaction.Request.Method, interaction.Request.URI)
	t.index[key] = append(t.index[key], index)
	return nil
}

func matchKey(method string, uri string) string {
	return strings.ToUpper(method) + " " + uri
}

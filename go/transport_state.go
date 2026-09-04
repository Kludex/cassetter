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
	for index, interaction := range t.cassette.Interactions {
		t.orders[index] = uint64(index)
		key := matchKey(interaction.Request.Method, interaction.Request.URI)
		t.index[key] = append(t.index[key], index)
	}
	t.nextOrder = uint64(len(t.cassette.Interactions))
	t.canRecord = t.config.mode == RecordModeNewEpisodes || t.config.mode == RecordModeAll ||
		t.config.mode == RecordModeRewrite || t.config.mode == RecordModeOnce && !exists
}

func (t *Transport) takeMatch(method string, uri string) (HTTPInteraction, bool) {
	t.mu.Lock()
	defer t.mu.Unlock()
	for _, candidate := range t.index[matchKey(method, uri)] {
		if !t.played[candidate] {
			t.played[candidate] = true
			return t.cassette.Interactions[candidate], true
		}
	}
	return HTTPInteraction{}, false
}

func (t *Transport) reserveOrder() uint64 {
	t.mu.Lock()
	defer t.mu.Unlock()
	order := t.nextOrder
	t.nextOrder++
	return order
}

func (t *Transport) record(interaction HTTPInteraction, order uint64) error {
	cassette := &Cassette{Version: 1, Interactions: []HTTPInteraction{interaction}}
	cassette.Scrub(t.config.security)
	interaction = cassette.Interactions[0]

	t.mu.Lock()
	defer t.mu.Unlock()
	index := len(t.cassette.Interactions)
	t.cassette.Interactions = append(t.cassette.Interactions, interaction)
	t.played = append(t.played, false)
	t.orders = append(t.orders, order)
	key := matchKey(interaction.Request.Method, interaction.Request.URI)
	t.index[key] = append(t.index[key], index)

	indices := make([]int, len(t.cassette.Interactions))
	for index := range indices {
		indices[index] = index
	}
	sort.SliceStable(indices, func(left int, right int) bool {
		return t.orders[indices[left]] < t.orders[indices[right]]
	})
	output := *t.cassette
	output.Interactions = make([]HTTPInteraction, 0, len(indices))
	for _, index := range indices {
		output.Interactions = append(output.Interactions, t.cassette.Interactions[index])
	}
	return output.Save(t.config.path)
}

func matchKey(method string, uri string) string {
	return strings.ToUpper(method) + " " + uri
}

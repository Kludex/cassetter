package cassetter

import "sort"

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
		t.saveEmpty = false
		return err
	}
	t.saveEmpty = false

	index := len(t.cassette.Interactions)
	t.cassette.Interactions = candidateInteractions
	t.played = append(t.played, false)
	t.orders = candidateOrders
	if t.usesMethodURIIndex() {
		request := t.matchingRequest(interaction.Request)
		key := matchKey(request.Method, request.URI)
		t.index[key] = append(t.index[key], index)
	}
	return nil
}

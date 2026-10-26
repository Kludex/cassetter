package cassetter

import "bytes"

func (t *Transport) record(interaction HTTPInteraction, order uint64) error {
	interaction = scrubbed(interaction, t.config.security)

	t.mu.Lock()
	defer t.mu.Unlock()
	if t.closed {
		return ErrTransportClosed
	}
	candidateInteractions := append([]HTTPInteraction(nil), t.cassette.Interactions...)
	candidateInteractions = append(candidateInteractions, interaction)
	candidateOrders := append([]uint64(nil), t.orders...)
	candidateOrders = append(candidateOrders, order)

	output := *t.cassette
	output.Interactions = orderedRecordings(candidateInteractions, candidateOrders)
	output.GRPCInteractions = orderedRecordings(t.cassette.GRPCInteractions, t.grpcOrders)
	output.WebSocketInteractions = orderedRecordings(t.cassette.WebSocketInteractions, t.webSocketOrders)
	if err := output.Save(t.config.path); err != nil {
		t.saveEmpty = false
		return err
	}
	t.saveEmpty = false

	index := len(t.cassette.Interactions)
	t.cassette.Interactions = candidateInteractions
	// The request that produced a recording has played it, so a repeat goes live.
	t.played = append(t.played, true)
	t.orders = candidateOrders
	if t.usesMethodURIIndex() {
		request := t.matchingRequest(interaction.Request)
		key := matchKey(request.Method, request.URI)
		t.index[key] = append(t.index[key], index)
	}
	return nil
}

func (t *Transport) verify(interaction HTTPInteraction, recorded HTTPResponse) error {
	interaction = scrubbed(interaction, t.config.security)
	live := interaction.Response
	recorded.Headers = recorded.Headers.Clone()
	recorded.Body.Content = normalizeJSONValueContent(recorded.Body.Content)
	if content, ok := recorded.Body.Content.([]byte); ok {
		recorded.Body.Content = bytes.Clone(content)
	}
	if t.config.beforeCompare != nil {
		recorded, live = t.config.beforeCompare(recorded, live)
	}
	diff, err := compareResponses(t.config.compare, recorded, live)
	if err != nil || diff == "" {
		return err
	}
	return &ResponseMismatchError{
		Path:   t.config.path,
		Method: interaction.Request.Method,
		URI:    interaction.Request.URI,
		Diff:   diff,
	}
}

func scrubbed(interaction HTTPInteraction, security SecurityConfig) HTTPInteraction {
	cassette := &Cassette{Version: 1, Interactions: []HTTPInteraction{interaction}}
	cassette.Scrub(security)
	return cassette.Interactions[0]
}

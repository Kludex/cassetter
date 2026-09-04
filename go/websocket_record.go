package cassetter

import "errors"

func (t *Transport) recordWebSocket(interaction WebSocketInteraction, order uint64) (err error) {
	cassette := &Cassette{
		Version:               1,
		Interactions:          []HTTPInteraction{},
		WebSocketInteractions: []WebSocketInteraction{interaction},
	}
	cassette.Scrub(t.config.security)
	interaction = cassette.WebSocketInteractions[0]

	t.mu.Lock()
	defer func() {
		delete(t.webSocketPending, order)
		if err != nil {
			t.recordErr = errors.Join(t.recordErr, err)
		}
		t.mu.Unlock()
	}()
	if t.closed {
		return ErrTransportClosed
	}
	candidateInteractions := append([]WebSocketInteraction(nil), t.cassette.WebSocketInteractions...)
	candidateInteractions = append(candidateInteractions, interaction)
	candidateOrders := append([]uint64(nil), t.webSocketOrders...)
	candidateOrders = append(candidateOrders, order)

	output := *t.cassette
	output.Interactions = orderedRecordings(t.cassette.Interactions, t.orders)
	output.GRPCInteractions = orderedRecordings(t.cassette.GRPCInteractions, t.grpcOrders)
	output.WebSocketInteractions = orderedRecordings(candidateInteractions, candidateOrders)
	if saveErr := output.Save(t.config.path); saveErr != nil {
		t.saveEmpty = false
		return saveErr
	}
	t.saveEmpty = false
	t.cassette.WebSocketInteractions = candidateInteractions
	t.webSocketPlayed = append(t.webSocketPlayed, false)
	t.webSocketOrders = candidateOrders
	return nil
}

package cassetter

import "errors"

func (t *Transport) recordGRPC(interaction GRPCInteraction, order uint64) (err error) {
	cassette := &Cassette{
		Version:          1,
		Interactions:     []HTTPInteraction{},
		GRPCInteractions: []GRPCInteraction{interaction},
	}
	cassette.Scrub(t.config.security)
	interaction = cassette.GRPCInteractions[0]

	t.mu.Lock()
	defer func() {
		delete(t.grpcPending, order)
		if err != nil {
			t.recordErr = errors.Join(t.recordErr, err)
		}
		t.mu.Unlock()
	}()
	if t.closed {
		return ErrTransportClosed
	}
	candidateInteractions := append([]GRPCInteraction(nil), t.cassette.GRPCInteractions...)
	candidateInteractions = append(candidateInteractions, interaction)
	candidateOrders := append([]uint64(nil), t.grpcOrders...)
	candidateOrders = append(candidateOrders, order)

	output := *t.cassette
	output.Interactions = orderedRecordings(t.cassette.Interactions, t.orders)
	output.GRPCInteractions = orderedRecordings(candidateInteractions, candidateOrders)
	output.WebSocketInteractions = orderedRecordings(t.cassette.WebSocketInteractions, t.webSocketOrders)
	if saveErr := output.Save(t.config.path); saveErr != nil {
		t.saveEmpty = false
		return saveErr
	}
	t.saveEmpty = false
	t.cassette.GRPCInteractions = candidateInteractions
	t.grpcPlayed = append(t.grpcPlayed, false)
	t.grpcOrders = candidateOrders
	return nil
}

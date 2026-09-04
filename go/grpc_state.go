package cassetter

import "errors"

func (t *Transport) takeGRPCMatch(method string) (GRPCInteraction, bool, error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.closed {
		return GRPCInteraction{}, false, ErrTransportClosed
	}
	fallback := -1
	for index, interaction := range t.cassette.GRPCInteractions {
		if interaction.Request.Method != method {
			continue
		}
		if !t.grpcPlayed[index] {
			t.grpcPlayed[index] = true
			return interaction, true, nil
		}
		if fallback < 0 {
			fallback = index
		}
	}
	if fallback >= 0 {
		return t.cassette.GRPCInteractions[fallback], true, nil
	}
	return GRPCInteraction{}, false, nil
}

func (t *Transport) reserveGRPCRecording(method string) (uint64, error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.closed {
		return 0, ErrTransportClosed
	}
	order := t.nextOrder
	t.nextOrder++
	t.grpcPending[order] = method
	return order, nil
}

func (t *Transport) finishGRPCRecording(order uint64, err error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	delete(t.grpcPending, order)
	if err != nil {
		t.recordErr = errors.Join(t.recordErr, err)
	}
}

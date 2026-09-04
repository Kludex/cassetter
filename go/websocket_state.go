package cassetter

import "errors"

func (t *Transport) takeWebSocketMatch(uri string) (WebSocketInteraction, bool, error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.closed {
		return WebSocketInteraction{}, false, ErrTransportClosed
	}
	probe := t.matchingWebSocketURI(uri)
	fallback := -1
	for index, interaction := range t.cassette.WebSocketInteractions {
		if t.matchingWebSocketURI(interaction.URI) != probe {
			continue
		}
		if !t.webSocketPlayed[index] {
			t.webSocketPlayed[index] = true
			return interaction, true, nil
		}
		if fallback < 0 {
			fallback = index
		}
	}
	if fallback >= 0 {
		return t.cassette.WebSocketInteractions[fallback], true, nil
	}
	return WebSocketInteraction{}, false, nil
}

func (t *Transport) matchingWebSocketURI(uri string) string {
	uri = scrubURI(uri, t.config.security.FilterQueryParameters, t.config.security.Replacement)
	if t.config.uriNormalizer != nil {
		return t.config.uriNormalizer(uri)
	}
	return uri
}

func (t *Transport) reserveWebSocketRecording(uri string) (uint64, error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.closed {
		return 0, ErrTransportClosed
	}
	order := t.nextOrder
	t.nextOrder++
	t.webSocketPending[order] = uri
	return order, nil
}

func (t *Transport) finishWebSocketRecording(order uint64, err error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	delete(t.webSocketPending, order)
	if err != nil {
		t.recordErr = errors.Join(t.recordErr, err)
	}
}

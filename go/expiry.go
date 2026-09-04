package cassetter

import (
	"fmt"
	"log"
	"os"
	"time"
)

func (t *Transport) checkExpiry() (bool, error) {
	if t.config.maxAge == nil {
		return false, nil
	}
	timestampCount := len(t.cassette.Interactions) + len(t.cassette.GRPCInteractions) +
		len(t.cassette.WebSocketInteractions)
	timestamps := make([]string, 0, timestampCount)
	for _, interaction := range t.cassette.Interactions {
		timestamps = append(timestamps, interaction.RecordedAt)
	}
	for _, interaction := range t.cassette.GRPCInteractions {
		timestamps = append(timestamps, interaction.RecordedAt)
	}
	for _, interaction := range t.cassette.WebSocketInteractions {
		timestamps = append(timestamps, interaction.RecordedAt)
	}
	var newest time.Time
	for _, timestamp := range timestamps {
		if timestamp == "" {
			continue
		}
		recordedAt, err := time.Parse(time.RFC3339Nano, timestamp)
		if err != nil {
			return false, fmt.Errorf("cassetter: parse recorded_at %q: %w", timestamp, err)
		}
		if recordedAt.After(newest) {
			newest = recordedAt
		}
	}
	if newest.IsZero() {
		return false, nil
	}
	now := time.Now().UTC()
	if !newest.Before(now.Add(-*t.config.maxAge)) {
		return false, nil
	}
	expired := &CassetteExpiredError{Path: t.config.path, Age: now.Sub(newest), MaxAge: *t.config.maxAge}
	switch t.config.expiryAction {
	case ExpiryWarn:
		log.Printf("cassetter warning: %v", expired)
		return false, nil
	case ExpiryFail:
		return false, expired
	case ExpiryRerecord:
		if err := os.Remove(t.config.path); err != nil {
			return false, fmt.Errorf("remove expired cassette: %w", err)
		}
		t.cassette = &Cassette{Version: 1, Interactions: []HTTPInteraction{}}
		return true, nil
	default:
		return false, fmt.Errorf("cassetter: unknown expiry action %q", t.config.expiryAction)
	}
}

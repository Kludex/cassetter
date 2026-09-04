package cassetter

import "fmt"

func (c *Cassette) validate() error {
	if c.Version != 0 && c.Version != 1 {
		return fmt.Errorf("unsupported cassette version %d", c.Version)
	}
	for index, interaction := range c.Interactions {
		if interaction.Request.Method == "" {
			return fmt.Errorf("interaction %d has an empty request method", index+1)
		}
		if interaction.Request.URI == "" {
			return fmt.Errorf("interaction %d has an empty request URI", index+1)
		}
		if interaction.Response.Status < 100 || interaction.Response.Status > 999 {
			return fmt.Errorf("interaction %d has invalid response status %d", index+1, interaction.Response.Status)
		}
	}
	for index, interaction := range c.GRPCInteractions {
		if interaction.Request.Method == "" {
			return fmt.Errorf("gRPC interaction %d has an empty request method", index+1)
		}
	}
	for index, interaction := range c.WebSocketInteractions {
		if interaction.URI == "" {
			return fmt.Errorf("WebSocket interaction %d has an empty URI", index+1)
		}
	}
	return nil
}

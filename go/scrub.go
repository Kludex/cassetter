package cassetter

// Scrub applies write-time secret filtering to every interaction.
func (c *Cassette) Scrub(config SecurityConfig) {
	for index := range c.Interactions {
		interaction := &c.Interactions[index]
		filterHeaders(interaction.Request.Headers, config.FilterHeaders)
		filterHeaders(interaction.Response.Headers, config.FilterHeaders)
		interaction.Request.URI = scrubURI(
			interaction.Request.URI,
			config.FilterQueryParameters,
			config.Replacement,
		)
		interaction.Request.Body = scrubBody(
			interaction.Request.Body,
			config.BodyScrubPatterns,
			config.Replacement,
		)
		interaction.Response.Body = scrubBody(
			interaction.Response.Body,
			config.BodyScrubPatterns,
			config.Replacement,
		)
		retagContentLength(interaction.Request.Headers, interaction.Request.Body)
		retagContentLength(interaction.Response.Headers, interaction.Response.Body)
	}
	for index := range c.GRPCInteractions {
		interaction := &c.GRPCInteractions[index]
		filterHeaders(interaction.Request.Metadata, config.FilterHeaders)
		filterHeaders(interaction.Response.Metadata, config.FilterHeaders)
		interaction.Request.Body = scrubBody(
			interaction.Request.Body,
			config.BodyScrubPatterns,
			config.Replacement,
		)
		interaction.Response.Body = scrubBody(
			interaction.Response.Body,
			config.BodyScrubPatterns,
			config.Replacement,
		)
		interaction.JSONDebug = scrubJSONContent(
			interaction.JSONDebug,
			config.BodyScrubPatterns,
			config.Replacement,
		)
	}
	for index := range c.WebSocketInteractions {
		interaction := &c.WebSocketInteractions[index]
		filterHeaders(interaction.Headers, config.FilterHeaders)
		interaction.URI = scrubURI(interaction.URI, config.FilterQueryParameters, config.Replacement)
		for frameIndex := range interaction.Frames {
			interaction.Frames[frameIndex].Body = scrubBody(
				interaction.Frames[frameIndex].Body,
				config.BodyScrubPatterns,
				config.Replacement,
			)
		}
	}
}

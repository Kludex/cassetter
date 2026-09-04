package cassetter

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"

	"gopkg.in/yaml.v3"
)

// Cassette contains recorded interactions in the cassetter v1 format.
type Cassette struct {
	Version               int                    `yaml:"version"`
	Interactions          []HTTPInteraction      `yaml:"interactions"`
	GRPCInteractions      []GRPCInteraction      `yaml:"grpc_interactions,omitempty"`
	WebSocketInteractions []WebSocketInteraction `yaml:"ws_interactions,omitempty"`
	extra                 map[string]yaml.Node
}

// Load reads a YAML or TOML cassette based on the path extension.
func Load(path string) (*Cassette, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read cassette: %w", err)
	}
	if isTOML(path) {
		return unmarshalTOML(content)
	}
	var cassette Cassette
	if err := yaml.Unmarshal(content, &cassette); err != nil {
		return nil, fmt.Errorf("parse cassette: %w", err)
	}
	if err := cassette.validate(); err != nil {
		return nil, err
	}
	return &cassette, nil
}

// Save atomically writes a YAML or TOML cassette based on the path extension.
func (c *Cassette) Save(path string) error {
	if err := c.validate(); err != nil {
		return err
	}
	var content []byte
	var err error
	if isTOML(path) {
		content, err = c.marshalTOML()
	} else {
		content, err = yaml.Marshal(c)
		if err != nil {
			err = fmt.Errorf("marshal cassette: %w", err)
		}
	}
	if err != nil {
		return err
	}
	parent := filepath.Dir(path)
	if err := os.MkdirAll(parent, 0o755); err != nil {
		return fmt.Errorf("create cassette directory: %w", err)
	}
	file, err := os.CreateTemp(parent, ".cassetter-*.tmp")
	if err != nil {
		return fmt.Errorf("create temporary cassette: %w", err)
	}
	temporary := file.Name()
	defer func() {
		_ = os.Remove(temporary)
	}()

	if info, statErr := os.Stat(path); statErr == nil {
		if err := file.Chmod(info.Mode()); err != nil {
			return errors.Join(fmt.Errorf("preserve cassette permissions: %w", err), file.Close())
		}
	} else if !errors.Is(statErr, os.ErrNotExist) {
		return errors.Join(fmt.Errorf("inspect cassette: %w", statErr), file.Close())
	}
	if _, err := file.Write(content); err != nil {
		return errors.Join(fmt.Errorf("write cassette: %w", err), file.Close())
	}
	if err := file.Sync(); err != nil {
		return errors.Join(fmt.Errorf("sync cassette: %w", err), file.Close())
	}
	if err := file.Close(); err != nil {
		return fmt.Errorf("close cassette: %w", err)
	}
	if err := os.Rename(temporary, path); err != nil {
		return fmt.Errorf("replace cassette: %w", err)
	}
	return nil
}

// MarshalYAML preserves unrecognized top-level sections.
func (c Cassette) MarshalYAML() (any, error) {
	var node yaml.Node
	value := struct {
		Version               int                    `yaml:"version"`
		Interactions          []HTTPInteraction      `yaml:"interactions"`
		GRPCInteractions      []GRPCInteraction      `yaml:"grpc_interactions,omitempty"`
		WebSocketInteractions []WebSocketInteraction `yaml:"ws_interactions,omitempty"`
	}{
		Version:               c.Version,
		Interactions:          c.Interactions,
		GRPCInteractions:      c.GRPCInteractions,
		WebSocketInteractions: c.WebSocketInteractions,
	}
	if value.Version == 0 {
		value.Version = 1
	}
	if value.Interactions == nil {
		value.Interactions = []HTTPInteraction{}
	}
	if err := node.Encode(value); err != nil {
		return nil, err
	}
	keys := make([]string, 0, len(c.extra))
	for key := range c.extra {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		keyNode := yaml.Node{Kind: yaml.ScalarNode, Tag: "!!str", Value: key}
		valueNode := c.extra[key]
		node.Content = append(node.Content, &keyNode, &valueNode)
	}
	return &node, nil
}

// UnmarshalYAML reads known fields and retains all other top-level fields.
func (c *Cassette) UnmarshalYAML(node *yaml.Node) error {
	var value struct {
		Version               int                    `yaml:"version"`
		Interactions          []HTTPInteraction      `yaml:"interactions"`
		GRPCInteractions      []GRPCInteraction      `yaml:"grpc_interactions,omitempty"`
		WebSocketInteractions []WebSocketInteraction `yaml:"ws_interactions,omitempty"`
	}
	if err := node.Decode(&value); err != nil {
		return err
	}
	if value.Version == 0 {
		value.Version = 1
	}
	c.Version = value.Version
	c.Interactions = value.Interactions
	c.GRPCInteractions = value.GRPCInteractions
	c.WebSocketInteractions = value.WebSocketInteractions
	c.extra = make(map[string]yaml.Node)
	for index := 0; index+1 < len(node.Content); index += 2 {
		key := node.Content[index].Value
		if key != "version" && key != "interactions" && key != "grpc_interactions" && key != "ws_interactions" {
			c.extra[key] = *node.Content[index+1]
		}
	}
	return nil
}

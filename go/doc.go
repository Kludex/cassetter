// Package cassetter records and replays HTTP, gRPC, and WebSocket interactions.
//
// Recordings use the shared cassetter YAML format. HTTP-only cassettes may also
// use TOML. New transports filter common credentials before every atomic write.
package cassetter

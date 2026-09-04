# cassetter-core

`cassetter-core` provides the cassette format, matching, filtering, and body
processing used by the cassetter SDKs.

```rust
use cassetter_core::cassette::Cassette;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let cassette = Cassette::new();
    cassette.save("cassette.yaml", None, None)?;
    Ok(())
}
```

Use a language SDK when you need client interception. The core crate provides
protocol-neutral data structures and persistence for custom integrations.

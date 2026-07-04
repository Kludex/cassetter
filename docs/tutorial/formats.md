# Cassette formats

Cassettes can be stored as **YAML** (the default) or **TOML**. The format is detected from the file extension: `.yaml` and `.yml` for YAML, `.toml` for TOML.

## YAML

The default, and the most readable. JSON bodies are stored as structured YAML:

```yaml
version: 1
interactions:
  - request:
      method: POST
      uri: https://api.openai.com/v1/chat/completions
      headers:
        content-type:
          - application/json
      body:
        type: json
        content:
          model: gpt-4o
          messages:
            - role: user
              content: Hello!
    response:
      status: 200
      body:
        type: json
        content:
          id: chatcmpl-abc123
          choices:
            - message:
                role: assistant
                content: Hi there!
    recorded_at: '2026-02-20T10:30:01Z'
```

Compare that to VCR.py, where the same body would be one long escaped string. When the API response changes, your git diff shows exactly which field changed.

## TOML

Use the `.toml` extension to get TOML cassettes:

```python
with use_cassette("cassette.toml"):
    ...
```

TOML loads about 2 times faster than YAML and produces about 12% smaller files. The tradeoff: TOML cannot represent `null` values or heterogeneous arrays, so body content is stored as a JSON string instead of as structure.

!!! tip
    Use YAML when humans read the cassettes, use TOML when you have thousands of interactions and load time matters.

## Convert between formats

The `cassetter` CLI converts existing cassettes:

```console
$ cassetter convert cassette.yaml cassette.toml
```

Convert a whole directory in place, changing extensions:

```console
$ cassetter convert tests/cassettes/ toml
```

Or convert into a separate output directory:

```console
$ cassetter convert tests/cassettes/ output/ --to toml
```

## Body types

Bodies are stored with an explicit type, so replay is always faithful:

| Type | Content |
|------|---------|
| `json` | Structured data, stored as YAML structure |
| `text` | Plain text, stored as a string |
| `binary` | Anything else, stored as hex |
| `none` | Empty body |

Compressed responses (gzip, brotli, zstd) are decompressed before recording, so the cassette always contains readable content.

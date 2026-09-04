# Release the Go module

Go ships as part of the [coordinated release](../RELEASING.md). A root
`vX.Y.Z` release publishes every ecosystem at the same version.

The release workflow validates the Go module on the latest Go 1.25 patch and
latest stable Go release. It runs race tests, vet, lint, and `govulncheck`
before creating the matching `go/vX.Y.Z` tag.

Go module versions need the directory prefix because the module lives in
`go/`. For example, root tag `v0.11.0` creates `go/v0.11.0` at the same commit.
The workflow refuses to move an existing tag.

## Verify the public module

```console
GOPROXY=https://proxy.golang.org go list -m github.com/Kludex/cassetter/go@v0.11.0
GOPROXY=direct go mod download github.com/Kludex/cassetter/go@v0.11.0
```

If validation fails before the Go tag exists, correct the code on `main` and
publish a new root version. If any package or tag already exists, follow the
coordinated release recovery steps. Never move or replace a published tag.

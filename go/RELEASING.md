# Release the Go module

Go module versions use repository tags prefixed with the module directory. For example, Go version `v0.1.0` uses the
Git tag `go/v0.1.0`. A root tag such as `v0.1.0` belongs to the Python and Node release workflow.

## Verify

```console
$ git switch main
$ git pull --ff-only
$ git status --short
$ (cd go && go mod verify)
$ (cd go && go test -race ./...)
$ (cd go && go vet ./...)
$ (cd go && golangci-lint run ./...)
$ (cd go && go run golang.org/x/vuln/cmd/govulncheck@v1.7.0 ./...)
```

Confirm the `main` CI workflow is green. Confirm the release version and notes in `go/CHANGELOG.md`.

## Tag

```console
$ git tag -a go/v0.1.0 -m "Release Go v0.1.0"
$ git push origin go/v0.1.0
```

The `Validate Go release` workflow checks the tag, module path, race tests, vet, and lint. Do not create the GitHub
release until this workflow passes.

## Publish the GitHub release

Create a non-draft GitHub release from the existing `go/v0.1.0` tag. A Go release does not upload a package artifact.
The Go module proxy reads the tagged `go/` directory directly. The PyPI workflow ignores tags that do not start with
`v`.

## Verify the public module

```console
$ GOPROXY=https://proxy.golang.org go list -m github.com/Kludex/cassetter/go@v0.1.0
$ GONOSUMDB=github.com/Kludex/cassetter GOPROXY=direct go mod download github.com/Kludex/cassetter/go@v0.1.0
```

If validation fails before the GitHub release exists, correct the code on `main` and publish a new version tag. Do not
move or replace a pushed tag. If the GitHub release already exists, inspect the release, tag, and proxy before taking
any recovery action.

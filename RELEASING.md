# Release cassetter

A coordinated release publishes Python, TypeScript, Rust, and Go from one root
`vX.Y.Z` tag. Every package uses the same version.

## Configure trusted publishing

Create these protected GitHub environments before the first coordinated
release.

| Environment | Registry package | Workflow |
| --- | --- | --- |
| `pypi` | `cassetter` | `.github/workflows/publish.yml` |
| `npm` | `cassetter` | `.github/workflows/publish.yml` |
| `crates-io` | `cassetter-core` | `.github/workflows/publish.yml` |

Configure each registry to trust its environment and this workflow. PyPI, npm,
and crates.io issue short-lived tokens through OpenID Connect (OIDC), so the
workflow does not store registry tokens.

The npm and crates.io packages may need an initial owner-controlled publication
before you can configure trusted publishing. Do not add a long-lived bootstrap
token to the workflow.

## Smoke-test release artifacts

```console
gh workflow run Release -f version=0.11.0
run_id=$(gh run list \
  --workflow Release \
  --limit 1 \
  --json databaseId \
  --jq '.[0].databaseId')
gh run watch "$run_id" --exit-status
```

Use the intended release version. A manual run executes the complete CI suite,
builds every artifact, installs the npm package, packages the Rust crate, and
validates the Go module. It does not publish or create a tag.

## Create the release tag

```console
git switch main
git pull --ff-only
git status --short
git tag -a v0.11.0 -m "Release v0.11.0"
git push origin v0.11.0
```

Use a stable canonical SemVer tag. The tag starts the `Release` workflow. The
workflow derives every package version from the tag and rejects prerelease,
build-metadata, and non-canonical versions.

The build jobs do not receive publishing credentials. Separate jobs publish
the verified artifacts through protected environments. The workflow also
creates `go/v0.11.0` at the same commit without moving an existing Go tag.

Do not create the GitHub release until the final `check coordinated release`
job passes.

## Publish the GitHub release

```console
gh release create v0.11.0 \
  --verify-tag \
  --title "v0.11.0 - <release theme>" \
  --notes-file release-notes.md
```

Use the existing root tag. One GitHub release describes the changes shared by
all four ecosystems.

## Verify every registry

```console
python -m pip index versions cassetter
npm view cassetter@0.11.0 version
cargo info cassetter-core@0.11.0
GOPROXY=https://proxy.golang.org go list -m github.com/Kludex/cassetter/go@v0.11.0
```

Confirm that each registry reports the same version. Confirm that
`go/v0.11.0` resolves to the same commit as `v0.11.0`.

## Recover from a failed release

Inspect every registry and both Git tags before retrying. Rerun failed jobs only
when successful publish jobs already created immutable package versions.

Do not move or replace a pushed tag. Correct source or artifact failures on
`main`, then publish a new patch version.

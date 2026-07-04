from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cassetter._core import (
    Cassette,
    SecurityConfig,
    scrub_grpc_interaction,
    scrub_interaction,
    scrub_ws_interaction,
)

EXTENSIONS = {".yaml", ".yml", ".toml"}


def scrub_cassette(cassette: Cassette, config: SecurityConfig) -> Cassette:
    """Return a copy of the cassette with security filtering applied to every interaction."""
    scrubbed = Cassette()
    for interaction in cassette.interactions:
        scrubbed.add_interaction(scrub_interaction(interaction, config))
    for grpc_interaction in cassette.grpc_interactions:
        scrubbed.add_grpc_interaction(scrub_grpc_interaction(grpc_interaction, config))
    for ws_interaction in cassette.ws_interactions:
        scrubbed.add_ws_interaction(scrub_ws_interaction(ws_interaction, config))
    return scrubbed


def convert_file(src: Path, dst: Path, *, scrub: bool = True) -> int:
    """Convert a single cassette file. Returns the number of interactions."""
    cassette = Cassette.load(str(src))
    if scrub:
        cassette = scrub_cassette(cassette, SecurityConfig())
    # Write via a temp file so an interrupted conversion never leaves a
    # truncated cassette. The temp name keeps the real extension because
    # save() detects the format from it.
    tmp = dst.with_suffix(f".tmp{dst.suffix}")
    cassette.save(str(tmp))
    tmp.replace(dst)
    return len(cassette)


def convert(args: argparse.Namespace) -> None:
    src = Path(args.input)
    dst = Path(args.output)
    scrub = not args.no_scrub

    if not src.exists():
        print(f"error: {src} not found", file=sys.stderr)
        sys.exit(1)

    if src.is_dir():
        to_ext = f".{args.to}" if args.to else None
        convert_directory(src, dst, force=args.force, to_ext=to_ext, scrub=scrub)
        return

    if src == dst and not args.force:
        print(f"error: converting {src} in place requires --force", file=sys.stderr)
        sys.exit(1)

    if src != dst and dst.exists() and not args.force:
        print(f"error: {dst} already exists (use --force to overwrite)", file=sys.stderr)
        sys.exit(1)

    n = convert_file(src, dst, scrub=scrub)
    print(f"Converted {n} interaction(s): {src} -> {dst}")


def convert_directory(src_dir: Path, dst: Path, *, force: bool, to_ext: str | None, scrub: bool = True) -> None:
    """Convert all cassette files in a directory tree.

    *dst* is either an existing/new directory, or a bare extension like ``toml``
    that determines the output format while keeping files in-place.
    *to_ext* overrides the target extension (e.g. ``.toml``) when writing to
    a separate output directory.
    """
    # Interpret dst as a target extension when it looks like one (no path separators, matches a known ext)
    target_ext = to_ext
    if not dst.suffix and f".{dst}" in EXTENSIONS:
        target_ext = target_ext or f".{dst}"
        out_dir = src_dir
    elif dst.suffix in EXTENSIONS and len(dst.parts) == 1:
        target_ext = target_ext or dst.suffix
        out_dir = src_dir
    else:
        out_dir = dst

    sources = sorted(p for p in src_dir.rglob("*") if p.suffix in EXTENSIONS and ".tmp" not in p.suffixes)
    if not sources:
        print(f"error: no cassette files found in {src_dir}", file=sys.stderr)
        sys.exit(1)

    converted = 0
    for src_file in sources:
        rel = src_file.relative_to(src_dir)
        if target_ext is not None:
            dst_file = out_dir / rel.with_suffix(target_ext)
        else:
            dst_file = out_dir / rel

        if src_file == dst_file and not force:
            print(f"skip: {src_file} (in-place rewrite requires --force)", file=sys.stderr)
            continue

        if src_file != dst_file and dst_file.exists() and not force:
            print(f"skip: {dst_file} already exists", file=sys.stderr)
            continue

        dst_file.parent.mkdir(parents=True, exist_ok=True)
        n = convert_file(src_file, dst_file, scrub=scrub)
        print(f"  {rel} -> {dst_file.relative_to(out_dir)} ({n} interaction(s))")
        converted += 1

    print(f"Converted {converted} file(s)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="cassetter", description="Cassetter CLI")
    subparsers = parser.add_subparsers(dest="command")

    convert_parser = subparsers.add_parser("convert", help="Convert cassettes between formats (yaml, toml)")
    convert_parser.add_argument("input", help="Source cassette file or directory")
    convert_parser.add_argument("output", help="Destination file, directory, or target format (e.g. 'toml')")
    convert_parser.add_argument("--force", "-f", action="store_true", help="Overwrite existing files")
    convert_parser.add_argument("--to", choices=["yaml", "toml"], help="Target format when output is a directory")
    convert_parser.add_argument(
        "--no-scrub",
        action="store_true",
        help="Skip security filtering (headers, query params, body fields) during conversion",
    )

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "convert":
        convert(args)


if __name__ == "__main__":
    main()

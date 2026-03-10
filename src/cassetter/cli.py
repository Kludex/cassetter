from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cassetter._core import Cassette

EXTENSIONS = {".yaml", ".yml", ".toml"}


def convert_file(src: Path, dst: Path) -> int:
    """Convert a single cassette file. Returns the number of interactions."""
    cassette = Cassette.load(str(src))
    cassette.save(str(dst))
    return len(cassette)


def convert(args: argparse.Namespace) -> None:
    src = Path(args.input)
    dst = Path(args.output)

    if not src.exists():
        print(f"error: {src} not found", file=sys.stderr)
        sys.exit(1)

    if src.is_dir():
        convert_directory(src, dst, force=args.force)
        return

    if dst.exists() and not args.force:
        print(f"error: {dst} already exists (use --force to overwrite)", file=sys.stderr)
        sys.exit(1)

    n = convert_file(src, dst)
    print(f"Converted {n} interaction(s): {src} -> {dst}")


def convert_directory(src_dir: Path, dst: Path, *, force: bool) -> None:
    """Convert all cassette files in a directory tree.

    *dst* is either an existing/new directory, or a bare extension like ``toml``
    that determines the output format while keeping files in-place.
    """
    # Interpret dst as a target extension when it looks like one (no path separators, matches a known ext)
    target_ext = None
    if not dst.suffix and f".{dst}" in EXTENSIONS:
        target_ext = f".{dst}"
        out_dir = src_dir
    elif dst.suffix in EXTENSIONS and len(dst.parts) == 1:
        target_ext = dst.suffix
        out_dir = src_dir
    else:
        out_dir = dst

    sources = sorted(p for p in src_dir.rglob("*") if p.suffix in EXTENSIONS)
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

        if src_file == dst_file:
            continue

        if dst_file.exists() and not force:
            print(f"skip: {dst_file} already exists", file=sys.stderr)
            continue

        dst_file.parent.mkdir(parents=True, exist_ok=True)
        n = convert_file(src_file, dst_file)
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

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "convert":
        convert(args)


if __name__ == "__main__":
    main()

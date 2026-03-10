from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cassetter._core import Cassette


def convert(args: argparse.Namespace) -> None:
    src = Path(args.input)
    dst = Path(args.output)

    if not src.exists():
        print(f"error: {src} not found", file=sys.stderr)
        sys.exit(1)

    if dst.exists() and not args.force:
        print(f"error: {dst} already exists (use --force to overwrite)", file=sys.stderr)
        sys.exit(1)

    cassette = Cassette.load(str(src))
    cassette.save(str(dst))

    src_ext = src.suffix.lstrip(".")
    dst_ext = dst.suffix.lstrip(".")
    n = len(cassette)
    print(f"Converted {n} interaction(s): {src_ext} -> {dst_ext}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="cassetter", description="Cassetter CLI")
    subparsers = parser.add_subparsers(dest="command")

    convert_parser = subparsers.add_parser("convert", help="Convert cassette between formats (yaml, toml)")
    convert_parser.add_argument("input", help="Source cassette file")
    convert_parser.add_argument("output", help="Destination cassette file")
    convert_parser.add_argument("--force", "-f", action="store_true", help="Overwrite destination if it exists")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "convert":
        convert(args)


if __name__ == "__main__":
    main()

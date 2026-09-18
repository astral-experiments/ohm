#!/usr/bin/env python3
"""Build the full-revision rustc driver against a matching compiler bootstrap."""

import argparse
from pathlib import Path

from measure_source import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bootstrap", type=lambda value: Path(value).resolve(), required=True
    )
    parser.add_argument(
        "--output", type=lambda value: Path(value).resolve(), required=True
    )
    parser.add_argument("--target", default="aarch64-apple-darwin")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    binary = build(
        args.bootstrap / args.target,
        args.output,
        source=Path(__file__).with_name("revision_driver.rs"),
        binary_name="revision-driver",
    )
    print(binary)


if __name__ == "__main__":
    main()

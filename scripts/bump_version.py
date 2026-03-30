#!/usr/bin/env python3
"""Bump the package version in pyproject.toml."""

from __future__ import annotations

import re
import sys
from pathlib import Path

VALID_PARTS = {"patch", "minor", "major"}


def bump_version(version: str, part: str) -> str:
    major, minor, patch = map(int, version.split("."))
    if part == "patch":
        patch += 1
    elif part == "minor":
        minor += 1
        patch = 0
    elif part == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        raise ValueError(f"Unsupported part: {part}")
    return f"{major}.{minor}.{patch}"


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in VALID_PARTS:
        valid = ", ".join(sorted(VALID_PARTS))
        print(f"Usage: python scripts/bump_version.py <{valid}>", file=sys.stderr)
        return 2

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    match = re.search(r'^version = "(\d+\.\d+\.\d+)"$', text, flags=re.MULTILINE)
    if match is None:
        print("Could not find [project] version in pyproject.toml", file=sys.stderr)
        return 1

    current = match.group(1)
    updated = bump_version(current, sys.argv[1])
    pyproject.write_text(
        text[: match.start(1)] + updated + text[match.end(1) :],
        encoding="utf-8",
    )
    print(updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

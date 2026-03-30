"""Version helpers for the transcript CLI."""

from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path

PACKAGE_NAME = "transcribe"


def get_version() -> str:
    """Return the installed package version."""
    return metadata.version(PACKAGE_NAME)


def get_commit_hash() -> str | None:
    """Return the installed Git commit hash when available."""
    try:
        dist = metadata.distribution(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return None

    direct_url = Path(dist.locate_file("direct_url.json"))
    if not direct_url.exists():
        return None

    try:
        payload = json.loads(direct_url.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    commit_id = payload.get("vcs_info", {}).get("commit_id")
    if not isinstance(commit_id, str) or not commit_id:
        return None
    return commit_id


def format_version_output() -> str:
    """Return a user-facing version string for the CLI."""
    version = get_version()
    commit_hash = get_commit_hash()
    if commit_hash:
        return f"transcribe {version} ({commit_hash[:7]})"
    return f"transcribe {version}"


__version__ = get_version()

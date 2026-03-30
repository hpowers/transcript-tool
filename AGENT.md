# AGENT.md

This repository contains a Python CLI for generating ElevenLabs transcripts from local audio files.

## Project layout

- `src/transcript_cli/`: CLI and transcription core
- `tests/`: unit and CLI tests
- `.github/workflows/ci.yml`: lint, type check, and test automation

## Setup

```bash
uv sync --group dev
```

## Common commands

```bash
uv run transcribe --help
transcribe --version
make install-tool
make upgrade-tool
make release-patch
make release-minor
make release-major
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

## Repo conventions

- Use Python 3.11+.
- Keep the CLI machine-friendly: stable errors, useful stdout, and no interactive prompts.
- Do not commit local secrets or generated transcript artifacts.
- Keep ElevenLabs API calls out of automated tests; mock the SDK instead.
- Preserve the output contract: `transcript_raw.json` and `transcript_conversation.txt`.
- `transcript_raw.json` is the full-fidelity source of truth; `transcript_conversation.txt` is intentionally edited for readability.
- `pyproject.toml` is the authoritative package version. Do not maintain a separate hard-coded version string.
- Pushing to `main` does not change the semantic version. Use the `make release-*` targets when making an intentional release.
- `transcribe --version` should report the installed package version and, when available, a short Git commit hash.

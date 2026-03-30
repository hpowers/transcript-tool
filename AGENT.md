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

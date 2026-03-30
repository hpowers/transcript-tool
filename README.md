# Transcript CLI

`transcript-cli` is a Python command-line tool for generating ElevenLabs transcripts from one or more local audio files.

- One input file: transcribes with diarization and creates a readable transcript labeled `Speaker 1`, `Speaker 2`, and so on.
- Multiple input files: treats each file as a separate speaker track, merges them into a multichannel WAV with `ffmpeg`, runs multichannel transcription, and labels speakers from the input filenames.

## Prerequisites

- Python 3.11+
- `ffmpeg` installed and available on `PATH` for multi-file runs
- `ELEVENLABS_API_KEY` set in your environment, or passed with `--api-key`

## Installation

Install from GitHub with `uv`:

```bash
uv tool install git+ssh://git@github.com/hpowers/transcript-tool.git
```

Update the installed tool to the latest version from GitHub:

```bash
make upgrade-tool
```

Or equivalently:

```bash
uv tool upgrade transcribe
```

Show the installed tool version:

```bash
transcribe --version
```

## Running The Latest Local Code

When you run the globally installed command:

```bash
transcribe ...
```

you are using the GitHub-installed tool on your `PATH`, not the current working tree in this repo.

To run the current repo version directly, use:

```bash
uv run transcribe --help
```

or:

```bash
uv run python -m transcript_cli --help
```

Recommended workflow:

- during development: use `uv run transcribe ...`
- when you want to refresh the globally installed command from GitHub: run `make upgrade-tool`
- when you want to verify what is installed: run `transcribe --version`

## Usage

Single-file diarized transcription:

```bash
transcribe episode.mp3 --output-dir ./artifacts
```

Multi-file multichannel transcription:

```bash
transcribe hunter.mp3 daniel.mp3 --output-dir ./artifacts
```

Override the API key explicitly:

```bash
transcribe episode.mp3 --api-key "$ELEVENLABS_API_KEY"
```

Keep the generated multichannel WAV:

```bash
transcribe hunter.mp3 daniel.mp3 --keep-merged-audio
```

Emit structured JSON for automation:

```bash
transcribe hunter.mp3 daniel.mp3 --json
```

## Outputs

Each run creates:

- `transcript_raw.json`
- `transcript_conversation.txt`

For multi-file runs, the tool also creates a temporary merged WAV. It is deleted by default unless `--keep-merged-audio` is passed.

## Automation Notes

`--json` prints a machine-readable payload to stdout with:

- run mode
- artifact paths
- merged-audio path when retained
- speaker labels
- ElevenLabs transcription ID when available

Errors remain human-readable and exit non-zero.

## Development

Install dev dependencies:

```bash
uv sync --group dev
```

Install the globally available CLI from GitHub:

```bash
make install-tool
```

Upgrade the installed CLI from GitHub:

```bash
make upgrade-tool
```

Bump the release version intentionally:

```bash
make release-patch
make release-minor
make release-major
```

Recommended release workflow:

1. Run one of the `make release-*` targets
2. Commit the version bump
3. Push to GitHub
4. Run `make upgrade-tool` on any machine that should pick up the new release
5. Verify with `transcribe --version`

Notes:

- pushing to `main` does not automatically change the semantic version
- `pyproject.toml` is the authoritative source for the package version
- `transcribe --version` may also include a short Git commit when install metadata provides it

Run checks:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

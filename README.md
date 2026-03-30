# Transcript CLI

`transcript-cli` is a Python command-line tool for generating ElevenLabs transcripts from one or more local audio files.

- One input file: transcribes with diarization and creates a readable transcript labeled `Speaker 1`, `Speaker 2`, and so on.
- Multiple input files: treats each file as a separate speaker track, merges them into a multichannel WAV with `ffmpeg`, runs multichannel transcription, and labels speakers from the input filenames.

## Prerequisites

- Python 3.11+
- `ffmpeg` installed and available on `PATH` for multi-file runs
- `ELEVENLABS_API_KEY` set in your environment, or passed with `--api-key`

## Installation

Install as a local tool with `uv`:

```bash
uv tool install .
```

Or run it directly from the repo:

```bash
uv run transcribe --help
```

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

Run checks:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```


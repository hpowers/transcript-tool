"""Typer CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from transcript_cli.core import TranscriptCliError, run_transcription

app = typer.Typer(
    add_completion=False,
    help="Generate ElevenLabs transcripts from one or more local audio files.",
    no_args_is_help=True,
)


@app.command()
def main(
    audio_files: Annotated[
        list[Path],
        typer.Argument(
            metavar="AUDIO_FILES...",
            help="One file for diarization, or multiple files for multichannel transcription.",
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            file_okay=False,
            dir_okay=True,
            writable=True,
            resolve_path=True,
            help="Directory where transcript artifacts will be written.",
        ),
    ] = Path("."),
    api_key: Annotated[
        str | None,
        typer.Option(
            "--api-key",
            help="ElevenLabs API key. Defaults to ELEVENLABS_API_KEY.",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite existing transcript artifacts in the output directory.",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Print a machine-readable result payload to stdout.",
        ),
    ] = False,
    keep_merged_audio: Annotated[
        bool,
        typer.Option(
            "--keep-merged-audio",
            help="Keep the generated multichannel WAV for multi-file runs.",
        ),
    ] = False,
) -> None:
    """Generate transcript artifacts for the given audio files."""

    try:
        result = run_transcription(
            audio_files,
            output_dir=output_dir,
            api_key=api_key,
            force=force,
            keep_merged_audio=keep_merged_audio,
        )
    except TranscriptCliError as exc:
        if json_output:
            typer.echo(json.dumps({"error": exc.message, "exit_code": exc.exit_code}))
        else:
            typer.secho(f"Error: {exc.message}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=exc.exit_code) from exc

    if json_output:
        typer.echo(json.dumps(result.to_dict(), indent=2))
        return

    typer.echo(f"Mode: {result.mode}")
    typer.echo(f"Raw transcript: {result.raw_path}")
    typer.echo(f"Readable transcript: {result.conversation_path}")
    if result.merged_audio_path is not None:
        typer.echo(f"Merged audio: {result.merged_audio_path}")
    if result.speaker_labels:
        typer.echo(f"Speakers: {', '.join(result.speaker_labels)}")
    if result.transcription_id:
        typer.echo(f"Transcription ID: {result.transcription_id}")

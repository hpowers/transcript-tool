from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from transcript_cli.cli import app
from transcript_cli.core import TranscriptCliError, TranscriptRunResult

runner = CliRunner()


def test_cli_version_flag(monkeypatch) -> None:
    monkeypatch.setattr(
        "transcript_cli.cli.format_version_output",
        lambda: "transcribe 0.2.1 (abcdef0)",
    )

    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "transcribe 0.2.1 (abcdef0)"


def test_cli_short_version_flag(monkeypatch) -> None:
    monkeypatch.setattr("transcript_cli.cli.format_version_output", lambda: "transcribe 0.2.1")

    result = runner.invoke(app, ["-V"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "transcribe 0.2.1"


def test_cli_json_output(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "episode.mp3"
    input_file.write_text("audio", encoding="utf-8")

    def fake_run_transcription(*args, **kwargs) -> TranscriptRunResult:
        return TranscriptRunResult(
            mode="diarized",
            raw_path=tmp_path / "transcript_raw.json",
            conversation_path=tmp_path / "transcript_conversation.txt",
            merged_audio_path=None,
            speaker_labels=["Speaker 1", "Speaker 2"],
            transcription_id="abc123",
            elapsed_seconds=12.5,
        )

    monkeypatch.setattr("transcript_cli.cli.run_transcription", fake_run_transcription)

    result = runner.invoke(app, [str(input_file), "--output-dir", str(tmp_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "diarized"
    assert payload["speaker_labels"] == ["Speaker 1", "Speaker 2"]
    assert "[preflight]" in result.stderr


def test_cli_human_output(monkeypatch, tmp_path: Path) -> None:
    left = tmp_path / "hunter.mp3"
    right = tmp_path / "daniel.mp3"
    left.write_text("left", encoding="utf-8")
    right.write_text("right", encoding="utf-8")

    def fake_run_transcription(*args, **kwargs) -> TranscriptRunResult:
        return TranscriptRunResult(
            mode="multichannel",
            raw_path=tmp_path / "transcript_raw.json",
            conversation_path=tmp_path / "transcript_conversation.txt",
            merged_audio_path=tmp_path / "multichannel_input.wav",
            speaker_labels=["Hunter", "Daniel"],
            transcription_id="xyz789",
            elapsed_seconds=9.0,
        )

    monkeypatch.setattr("transcript_cli.cli.run_transcription", fake_run_transcription)

    result = runner.invoke(app, [str(left), str(right), "--output-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert "Mode: multichannel" in result.stdout
    assert "Speakers: Hunter, Daniel" in result.stdout
    assert "Elapsed:" in result.stdout
    assert "[preflight]" in result.stderr


def test_cli_returns_structured_json_errors(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "episode.mp3"
    input_file.write_text("audio", encoding="utf-8")

    def fake_run_transcription(*args, **kwargs) -> TranscriptRunResult:
        raise TranscriptCliError("broken input", exit_code=2)

    monkeypatch.setattr("transcript_cli.cli.run_transcription", fake_run_transcription)

    result = runner.invoke(app, [str(input_file), "--json"])

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload == {"error": "broken input", "exit_code": 2}
    assert "[preflight]" in result.stderr


def test_cli_reports_stage_aware_errors(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "episode.mp3"
    input_file.write_text("audio", encoding="utf-8")

    def fake_run_transcription(*args, **kwargs) -> TranscriptRunResult:
        raise TranscriptCliError("transcription request failed: timeout", exit_code=4)

    monkeypatch.setattr("transcript_cli.cli.run_transcription", fake_run_transcription)

    result = runner.invoke(app, [str(input_file)])

    assert result.exit_code == 4
    assert "Error: transcription request failed: timeout" in result.stderr

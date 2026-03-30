from __future__ import annotations

from pathlib import Path

import pytest

from transcript_cli.core import (
    TranscriptCliError,
    build_multi_file_turns,
    build_single_file_turns,
    build_turns,
    ensure_output_paths,
    sanitize_speaker_name,
    validate_audio_files,
)


def test_sanitize_speaker_name_uses_filename_stem() -> None:
    assert sanitize_speaker_name(Path("hunter-powers_final.mp3"), 1) == "Hunter Powers Final"


def test_build_turns_groups_by_speaker_and_gap() -> None:
    turns = build_turns(
        [
            {"speaker": "Hunter", "start": 0.0, "end": 0.2, "text": "Hello"},
            {"speaker": "Hunter", "start": 0.3, "end": 0.5, "text": "there"},
            {"speaker": "Daniel", "start": 1.4, "end": 1.6, "text": "Hi"},
        ]
    )

    assert [(turn.speaker, turn.text) for turn in turns] == [
        ("Hunter", "Hello there"),
        ("Daniel", "Hi"),
    ]


def test_build_single_file_turns_numbers_speakers() -> None:
    turns, labels = build_single_file_turns(
        {
            "words": [
                {"speaker_id": "speaker_7", "start": 0.0, "end": 0.1, "text": "Hello"},
                {"speaker_id": "speaker_7", "start": 0.2, "end": 0.4, "text": "world"},
                {"speaker_id": "speaker_1", "start": 1.0, "end": 1.2, "text": "Hi"},
            ]
        }
    )

    assert labels == ["Speaker 1", "Speaker 2"]
    assert [(turn.speaker, turn.text) for turn in turns] == [
        ("Speaker 1", "Hello world"),
        ("Speaker 2", "Hi"),
    ]


def test_build_multi_file_turns_uses_filename_labels() -> None:
    turns, labels = build_multi_file_turns(
        {
            "transcripts": [
                {
                    "channel_index": 0,
                    "words": [{"start": 0.0, "end": 0.2, "text": "Hello"}],
                },
                {
                    "channel_index": 1,
                    "words": [{"start": 0.5, "end": 0.7, "text": "Hi"}],
                },
            ]
        },
        [Path("hunter.mp3"), Path("daniel.mp3")],
    )

    assert labels == ["Hunter", "Daniel"]
    assert [(turn.speaker, turn.text) for turn in turns] == [
        ("Hunter", "Hello"),
        ("Daniel", "Hi"),
    ]


def test_validate_audio_files_rejects_too_many(tmp_path: Path) -> None:
    files = []
    for index in range(6):
        path = tmp_path / f"speaker-{index}.wav"
        path.write_text("x", encoding="utf-8")
        files.append(path)

    with pytest.raises(TranscriptCliError, match="at most 5 input files"):
        validate_audio_files(files)


def test_ensure_output_paths_requires_force_for_existing_files(tmp_path: Path) -> None:
    (tmp_path / "transcript_raw.json").write_text("{}", encoding="utf-8")

    with pytest.raises(TranscriptCliError, match="Pass --force"):
        ensure_output_paths(tmp_path, force=False, keep_merged_audio=False)

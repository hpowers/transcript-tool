from __future__ import annotations

from pathlib import Path

import pytest

from transcript_cli.core import (
    TranscriptCliError,
    TranscriptTurn,
    build_multi_file_turns,
    build_readable_turns,
    build_single_file_turns,
    build_turns,
    ensure_output_paths,
    format_timestamp,
    sanitize_speaker_name,
    validate_audio_files,
    write_conversation,
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

    assert [(turn.speaker, turn.start, turn.end, turn.text) for turn in turns] == [
        ("Hunter", 0.0, 0.5, "Hello there"),
        ("Daniel", 1.4, 1.6, "Hi"),
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
    assert [(turn.speaker, turn.start, turn.text) for turn in turns] == [
        ("Speaker 1", 0.0, "Hello world"),
        ("Speaker 2", 1.0, "Hi"),
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
    assert [(turn.speaker, turn.start, turn.text) for turn in turns] == [
        ("Hunter", 0.0, "Hello"),
        ("Daniel", 0.5, "Hi"),
    ]


def test_format_timestamp_renders_minutes_seconds_and_hundredths() -> None:
    assert format_timestamp(0.0) == "00:00.00"
    assert format_timestamp(141.74) == "02:21.74"


def test_build_readable_turns_merges_adjacent_same_speaker() -> None:
    turns = build_readable_turns(
        [
            TranscriptTurn(speaker="Hunter", start=0.0, end=0.3, text="Hello"),
            TranscriptTurn(speaker="Hunter", start=4.0, end=4.3, text="again"),
            TranscriptTurn(speaker="Daniel", start=5.0, end=5.3, text="Hi"),
        ],
        merge_same_speaker=True,
    )

    assert [(turn.speaker, turn.start, turn.end, turn.text) for turn in turns] == [
        ("Hunter", 0.0, 4.3, "Hello again"),
        ("Daniel", 5.0, 5.3, "Hi"),
    ]


def test_build_readable_turns_drops_noise_only_turns() -> None:
    turns = build_readable_turns(
        [
            TranscriptTurn(speaker="Hunter", start=0.0, end=0.3, text="Hello"),
            TranscriptTurn(speaker="Daniel", start=0.4, end=0.5, text="[background noise]"),
            TranscriptTurn(speaker="Hunter", start=5.0, end=5.2, text="again"),
        ],
        merge_same_speaker=True,
    )

    assert [(turn.speaker, turn.text) for turn in turns] == [
        ("Hunter", "Hello again"),
    ]


def test_build_readable_turns_drops_filler_micro_turns() -> None:
    turns = build_readable_turns(
        [
            TranscriptTurn(speaker="Hunter", start=0.0, end=0.3, text="Hello"),
            TranscriptTurn(speaker="Daniel", start=0.4, end=0.5, text="Uh,"),
            TranscriptTurn(speaker="Hunter", start=0.8, end=1.1, text="again"),
        ],
        merge_same_speaker=True,
    )

    assert [(turn.speaker, turn.text) for turn in turns] == [
        ("Hunter", "Hello again"),
    ]


def test_build_readable_turns_keeps_meaningful_short_turns() -> None:
    turns = build_readable_turns(
        [
            TranscriptTurn(speaker="Hunter", start=0.0, end=0.3, text="Hello"),
            TranscriptTurn(speaker="Daniel", start=0.4, end=0.5, text="Wait."),
            TranscriptTurn(speaker="Hunter", start=0.8, end=1.1, text="again"),
        ],
        merge_same_speaker=True,
    )

    assert [(turn.speaker, turn.text) for turn in turns] == [
        ("Hunter", "Hello"),
        ("Daniel", "Wait."),
        ("Hunter", "again"),
    ]


def test_build_single_file_turns_uses_longer_pause_threshold_for_single_speaker() -> None:
    turns, labels = build_single_file_turns(
        {
            "words": [
                {"speaker_id": "speaker_0", "start": 0.0, "end": 0.1, "text": "Hello"},
                {"speaker_id": "speaker_0", "start": 2.5, "end": 2.8, "text": "again"},
                {"speaker_id": "speaker_0", "start": 7.5, "end": 7.7, "text": "later"},
            ]
        }
    )

    assert labels == ["Speaker 1"]
    assert [(turn.speaker, turn.start, turn.text) for turn in turns] == [
        ("Speaker 1", 0.0, "Hello again"),
        ("Speaker 1", 7.5, "later"),
    ]


def test_write_conversation_formats_timestamped_blocks(tmp_path: Path) -> None:
    output_path = tmp_path / "transcript_conversation.txt"

    write_conversation(
        output_path,
        [
            TranscriptTurn(speaker="Daniel", start=141.74, end=145.0, text="Hello there"),
        ],
    )

    assert output_path.read_text(encoding="utf-8") == "Daniel (02:21.74)\nHello there\n"


def test_write_conversation_separates_blocks_with_blank_lines(tmp_path: Path) -> None:
    output_path = tmp_path / "transcript_conversation.txt"

    write_conversation(
        output_path,
        [
            TranscriptTurn(speaker="Hunter", start=0.0, end=1.0, text="Hello"),
            TranscriptTurn(speaker="Daniel", start=2.0, end=3.0, text="Hi"),
        ],
    )

    assert (
        output_path.read_text(encoding="utf-8")
        == "Hunter (00:00.00)\nHello\n\nDaniel (00:02.00)\nHi\n"
    )


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

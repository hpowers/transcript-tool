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
    build_turns_by_speaker,
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


def test_build_multi_file_turns_ignores_audio_events() -> None:
    turns, labels = build_multi_file_turns(
        {
            "transcripts": [
                {
                    "channel_index": 0,
                    "words": [
                        {
                            "start": 0.0,
                            "end": 10.0,
                            "text": "[background noise]",
                            "type": "audio_event",
                        },
                        {"start": 10.1, "end": 10.3, "text": "Hello", "type": "word"},
                    ],
                },
                {
                    "channel_index": 1,
                    "words": [{"start": 10.5, "end": 10.7, "text": "Hi", "type": "word"}],
                },
            ]
        },
        [Path("hunter.mp3"), Path("daniel.mp3")],
    )

    assert labels == ["Hunter", "Daniel"]
    assert [(turn.speaker, turn.start, turn.end, turn.text) for turn in turns] == [
        ("Hunter", 10.1, 10.3, "Hello"),
        ("Daniel", 10.5, 10.7, "Hi"),
    ]


def test_build_turns_by_speaker_keeps_overlapping_utterances_together() -> None:
    turns = build_turns_by_speaker(
        [
            {"speaker": "Hunter", "start": 0.0, "end": 0.2, "text": "I"},
            {"speaker": "Daniel", "start": 0.1, "end": 0.3, "text": "but"},
            {"speaker": "Hunter", "start": 0.4, "end": 0.6, "text": "think"},
            {"speaker": "Daniel", "start": 0.5, "end": 0.7, "text": "certainly"},
        ]
    )

    assert [(turn.speaker, turn.start, turn.end, turn.text) for turn in turns] == [
        ("Hunter", 0.0, 0.6, "I think"),
        ("Daniel", 0.1, 0.7, "but certainly"),
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


def test_build_readable_turns_removes_filler_lead_ins() -> None:
    turns = build_readable_turns(
        [
            TranscriptTurn(
                speaker="Daniel",
                start=0.0,
                end=1.0,
                text="Uh, I mean, you know, we should go.",
            ),
        ],
        merge_same_speaker=True,
    )

    assert [(turn.speaker, turn.text) for turn in turns] == [
        ("Daniel", "We should go."),
    ]


def test_build_readable_turns_collapses_stutter_prefixes() -> None:
    turns = build_readable_turns(
        [
            TranscriptTurn(speaker="Hunter", start=0.0, end=1.0, text="I, I think it works."),
            TranscriptTurn(speaker="Daniel", start=2.0, end=3.0, text="it, it, it was a lot."),
        ],
        merge_same_speaker=True,
    )

    assert [(turn.speaker, turn.text) for turn in turns] == [
        ("Hunter", "I think it works."),
        ("Daniel", "It was a lot."),
    ]


def test_build_readable_turns_keeps_meaningful_short_questions() -> None:
    turns = build_readable_turns(
        [
            TranscriptTurn(speaker="Daniel", start=0.0, end=1.0, text="Is it AI related?"),
        ],
        merge_same_speaker=True,
    )

    assert [(turn.speaker, turn.text) for turn in turns] == [
        ("Daniel", "Is it AI related?"),
    ]


def test_build_readable_turns_drops_overlapping_micro_turns() -> None:
    turns = build_readable_turns(
        [
            TranscriptTurn(
                speaker="Hunter",
                start=0.0,
                end=10.0,
                text="One of the packages a lot of AI infrastructure relies on is called LiteLLM.",
            ),
            TranscriptTurn(speaker="Daniel", start=2.0, end=2.2, text="I"),
            TranscriptTurn(speaker="Daniel", start=5.0, end=5.2, text="did."),
            TranscriptTurn(speaker="Daniel", start=6.0, end=6.2, text="Yeah."),
            TranscriptTurn(
                speaker="Daniel",
                start=20.0,
                end=24.0,
                text="Yep. It was live for about an hour.",
            ),
        ],
        merge_same_speaker=True,
    )

    assert [(turn.speaker, turn.text) for turn in turns] == [
        ("Hunter", "One of the packages a lot of AI infrastructure relies on is called LiteLLM."),
        ("Daniel", "Yep. It was live for about an hour."),
    ]


def test_build_readable_turns_drops_overlap_heavy_backchannels() -> None:
    turns = build_readable_turns(
        [
            TranscriptTurn(
                speaker="Daniel",
                start=0.0,
                end=6.0,
                text="This is what's called a supply chain attack, I believe.",
            ),
            TranscriptTurn(speaker="Hunter", start=1.0, end=1.2, text="Okay."),
            TranscriptTurn(speaker="Hunter", start=1.5, end=1.7, text="Right."),
            TranscriptTurn(speaker="Hunter", start=2.0, end=2.2, text="Yeah."),
        ],
        merge_same_speaker=True,
    )

    assert [(turn.speaker, turn.text) for turn in turns] == [
        ("Daniel", "This is what's called a supply chain attack, I believe."),
    ]


def test_build_readable_turns_repairs_interrupted_same_speaker_clause() -> None:
    turns = build_readable_turns(
        [
            TranscriptTurn(
                speaker="Hunter",
                start=0.0,
                end=5.0,
                text='Someone put in a little bit of extra that said, "Hey, next time',
            ),
            TranscriptTurn(
                speaker="Daniel",
                start=3.0,
                end=4.0,
                text="Yep. It was live for about an hour.",
            ),
            TranscriptTurn(
                speaker="Hunter",
                start=6.0,
                end=9.0,
                text='you do some cool AI stuff, share your passwords." It got released.',
            ),
        ],
        merge_same_speaker=True,
    )

    assert [(turn.speaker, turn.text) for turn in turns] == [
        (
            "Hunter",
            'Someone put in a little bit of extra that said, "Hey, next time you do some '
            'cool AI stuff, share your passwords."',
        ),
        ("Daniel", "Yep. It was live for about an hour."),
        ("Hunter", "It got released."),
    ]


def test_build_readable_turns_keeps_single_block_for_long_turns() -> None:
    turns = build_readable_turns(
        [
            TranscriptTurn(
                speaker="Daniel",
                start=0.0,
                end=20.0,
                text=(
                    "Sentence one explains the setup. Sentence two adds more detail. "
                    "Sentence three keeps going with the argument. Sentence four continues the "
                    "same idea in plain language. Sentence five expands the example with more "
                    "context. Sentence six pushes it a little further. Sentence seven lands the "
                    "point with a conclusion. Sentence eight restates the takeaway in practical "
                    "terms. Sentence nine adds one more example for clarity. Sentence ten closes "
                    "the paragraph with a final observation."
                ),
            )
        ],
        merge_same_speaker=True,
    )

    assert len(turns) == 1
    assert "\n\n" not in turns[0].text


def test_build_readable_turns_removes_inline_fillers() -> None:
    turns = build_readable_turns(
        [
            TranscriptTurn(
                speaker="Hunter",
                start=0.0,
                end=2.0,
                text="Something is, uh, amiss, um, and it really is.",
            ),
        ],
        merge_same_speaker=True,
    )

    assert [(turn.speaker, turn.text) for turn in turns] == [
        ("Hunter", "Something is amiss, and it really is."),
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
        ("Speaker 1", 7.5, "Later"),
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


def test_write_conversation_does_not_render_overlap_annotations(tmp_path: Path) -> None:
    output_path = tmp_path / "transcript_conversation.txt"

    write_conversation(
        output_path,
        [
            TranscriptTurn(
                speaker="Hunter",
                start=0.0,
                end=1.0,
                text="I think it was way more than that.",
            ),
            TranscriptTurn(
                speaker="Daniel",
                start=0.1,
                end=0.8,
                text="but it certainly is low enough.",
            ),
        ],
    )

    assert (
        output_path.read_text(encoding="utf-8")
        == "Hunter (00:00.00)\nI think it was way more than that.\n\n"
        "Daniel (00:00.10)\nbut it certainly is low enough.\n"
    )


def test_demo_regression_drops_daniel_micro_fragments() -> None:
    turns = build_readable_turns(
        [
            TranscriptTurn(
                speaker="Hunter",
                start=292.12,
                end=334.95,
                text=(
                    "Some- something is, uh, amiss. Um, you know, one of the, uh, packages "
                    "or well, like one of the pieces of software that a lot of the AI, um, "
                    "uh, infrastructure relies upon is called LiteLLM."
                ),
            ),
            TranscriptTurn(speaker="Daniel", start=302.34, end=304.66, text="I"),
            TranscriptTurn(speaker="Daniel", start=308.74, end=308.92, text="did."),
            TranscriptTurn(speaker="Daniel", start=309.82, end=310.22, text="Yeah."),
            TranscriptTurn(
                speaker="Daniel",
                start=326.40,
                end=342.20,
                text="Yep. It was live for about an hour.",
            ),
        ],
        merge_same_speaker=True,
    )

    assert [(turn.speaker, turn.start, turn.text) for turn in turns] == [
        (
            "Hunter",
            292.12,
            "Something is amiss. One of the packages or well, like one of the pieces of software "
            "that a lot of the AI infrastructure relies upon is called LiteLLM.",
        ),
        ("Daniel", 326.40, "Yep. It was live for about an hour."),
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

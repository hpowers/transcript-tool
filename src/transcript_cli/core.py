"""Core transcription workflow for the transcript CLI."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, cast

from elevenlabs import ElevenLabs

RAW_TRANSCRIPT_FILENAME = "transcript_raw.json"
CONVERSATION_TRANSCRIPT_FILENAME = "transcript_conversation.txt"
MERGED_AUDIO_FILENAME = "multichannel_input.wav"
DEFAULT_MODEL_ID = "scribe_v2"
TURN_GAP_SECONDS = 0.7
SINGLE_SPEAKER_TURN_GAP_SECONDS = 3.0
DISPOSABLE_MICRO_TURN_MAX_TOKENS = 3
SUBSTANTIVE_TURN_MIN_TOKENS = 4
READABLE_MERGE_GAP_SECONDS = 6.0
SUBSTANTIVE_LOOKAHEAD_SECONDS = 30.0
CLAUSE_REPAIR_LOOKAHEAD_SECONDS = 12.0
CLAUSE_REPAIR_MAX_INTERVENING_TURNS = 2
FILLER_LEAD_IN_PHRASES = {
    "ah",
    "eh",
    "er",
    "erm",
    "hmm",
    "hm",
    "mhm",
    "mm",
    "mmhmm",
    "mmhm",
    "uh",
    "uhhuh",
    "uh-huh",
    "um",
    "you know",
    "i mean",
}
INLINE_FILLER_WORDS = {
    "ah",
    "eh",
    "er",
    "erm",
    "hm",
    "hmm",
    "mhm",
    "mm",
    "mmhm",
    "mmhmm",
    "uh",
    "um",
}
BACKCHANNEL_PHRASES = {
    "all right",
    "hey",
    "okay",
    "ok",
    "right",
    "uh huh",
    "well",
    "yeah",
    "yep",
    "yes",
}
BACKCHANNEL_TOKENS = {
    "all",
    "hey",
    "huh",
    "hmm",
    "mhm",
    "mm",
    "mmhm",
    "mmhmm",
    "ok",
    "okay",
    "right",
    "uh",
    "well",
    "yeah",
    "yep",
    "yes",
}
FRAGMENT_PHRASES = {
    "did",
    "i",
    "opening",
    "otherwise",
}
FRAGMENT_TOKENS = {
    "am",
    "are",
    "did",
    "do",
    "does",
    "had",
    "has",
    "have",
    "he",
    "i",
    "is",
    "it",
    "she",
    "that",
    "there",
    "they",
    "this",
    "was",
    "we",
    "were",
    "you",
}
CLAUSE_CONTINUATION_STARTERS = {
    "and",
    "because",
    "but",
    "for",
    "if",
    "it",
    "or",
    "so",
    "that",
    "the",
    "they",
    "this",
    "to",
    "we",
    "which",
}
INCOMPLETE_ENDING_TOKENS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "because",
    "but",
    "for",
    "from",
    "if",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "so",
    "that",
    "the",
    "their",
    "there",
    "these",
    "this",
    "those",
    "to",
    "was",
    "were",
    "with",
}
MULTICHANNEL_LAYOUTS = {
    2: "stereo",
    3: "3.0",
    4: "4.0",
    5: "5.0",
}
HEARTBEAT_INTERVAL_SECONDS = 15.0

Reporter = Callable[[str, str], None]


class TranscriptCliError(Exception):
    """A user-facing error with a deterministic exit code."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


@dataclass(slots=True)
class TranscriptTurn:
    speaker: str
    start: float
    end: float
    text: str


@dataclass(slots=True)
class TranscriptRunResult:
    mode: str
    raw_path: Path
    conversation_path: Path
    merged_audio_path: Path | None
    speaker_labels: list[str]
    transcription_id: str | None
    elapsed_seconds: float

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["raw_path"] = str(self.raw_path)
        payload["conversation_path"] = str(self.conversation_path)
        payload["merged_audio_path"] = (
            str(self.merged_audio_path) if self.merged_audio_path else None
        )
        return payload


def resolve_api_key(api_key: str | None) -> str:
    resolved = api_key or os.getenv("ELEVENLABS_API_KEY")
    if not resolved:
        raise TranscriptCliError(
            "Missing ElevenLabs API key. Set ELEVENLABS_API_KEY or pass --api-key.",
            exit_code=2,
        )
    return resolved


def detect_mode(audio_files: list[Path]) -> str:
    return "diarized" if len(audio_files) == 1 else "multichannel"


def validate_audio_files(audio_files: list[Path]) -> list[Path]:
    if not audio_files:
        raise TranscriptCliError("Pass at least one audio file.", exit_code=2)
    if len(audio_files) > 5:
        raise TranscriptCliError(
            "ElevenLabs multichannel transcription supports at most 5 input files.",
            exit_code=2,
        )

    resolved: list[Path] = []
    missing: list[str] = []
    for audio_file in audio_files:
        path = audio_file.expanduser().resolve()
        if not path.exists() or not path.is_file():
            missing.append(str(audio_file))
            continue
        resolved.append(path)

    if missing:
        raise TranscriptCliError(
            f"Input file not found: {', '.join(missing)}.",
            exit_code=2,
        )
    return resolved


def detect_speaker_labels(audio_files: list[Path]) -> list[str]:
    if len(audio_files) <= 1:
        return []
    return [sanitize_speaker_name(path, index + 1) for index, path in enumerate(audio_files)]


def ensure_output_paths(
    output_dir: Path,
    *,
    force: bool,
    keep_merged_audio: bool,
) -> tuple[Path, Path, Path | None]:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / RAW_TRANSCRIPT_FILENAME
    conversation_path = output_dir / CONVERSATION_TRANSCRIPT_FILENAME
    merged_path = output_dir / MERGED_AUDIO_FILENAME if keep_merged_audio else None

    required_paths = [raw_path, conversation_path]
    if merged_path is not None:
        required_paths.append(merged_path)

    if not force:
        collisions = [str(path) for path in required_paths if path.exists()]
        if collisions:
            raise TranscriptCliError(
                "Refusing to overwrite existing files. Pass --force to replace them: "
                + ", ".join(collisions),
                exit_code=2,
            )

    return raw_path, conversation_path, merged_path


def create_client(api_key: str) -> ElevenLabs:
    return ElevenLabs(api_key=api_key)


def to_jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, str | int | float | bool):
        return obj
    if isinstance(obj, list | tuple):
        return [to_jsonable(item) for item in obj]
    if isinstance(obj, dict):
        return {str(key): to_jsonable(value) for key, value in obj.items()}
    if hasattr(obj, "model_dump"):
        return to_jsonable(obj.model_dump())
    if hasattr(obj, "dict"):
        return to_jsonable(obj.dict())
    if hasattr(obj, "__dict__"):
        return to_jsonable(vars(obj))
    return str(obj)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_conversation(path: Path, turns: list[TranscriptTurn]) -> None:
    if not turns:
        path.write_text("No speech detected.\n", encoding="utf-8")
        return
    rendered = "\n\n".join(
        f"{turn.speaker} ({format_timestamp(turn.start)})\n{turn.text}" for turn in turns
    )
    path.write_text(rendered + "\n", encoding="utf-8")


def sanitize_speaker_name(path: Path, index: int) -> str:
    cleaned = re.sub(r"[_-]+", " ", path.stem)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return f"Speaker {index}"
    return " ".join(part.capitalize() for part in cleaned.split(" "))


def _run_with_heartbeat(
    fn: Callable[[], dict[str, Any]],
    *,
    reporter: Reporter | None,
) -> dict[str, Any]:
    if reporter is None:
        return fn()

    start_time = time.monotonic()
    stop_event = threading.Event()

    def heartbeat() -> None:
        while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
            elapsed = time.monotonic() - start_time
            reporter("wait", f"Still waiting on ElevenLabs ({elapsed:.1f}s elapsed)")

    worker = threading.Thread(target=heartbeat, daemon=True)
    worker.start()
    try:
        return fn()
    finally:
        stop_event.set()
        worker.join(timeout=0.1)


def normalize_word_entries(
    words: list[dict[str, Any]],
    label_map: dict[str, str],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for word in words:
        if str(word.get("type", "word")) == "audio_event":
            continue
        text = str(word.get("text", "")).strip()
        if not text:
            continue
        speaker_id = str(word.get("speaker_id", "speaker_0"))
        normalized.append(
            {
                "speaker": label_map.get(speaker_id, speaker_id),
                "start": float(word.get("start", 0.0)),
                "end": float(word.get("end", 0.0)),
                "text": text,
            }
        )
    return normalized


def build_turns(
    words: list[dict[str, Any]],
    *,
    turn_gap_seconds: float = TURN_GAP_SECONDS,
) -> list[TranscriptTurn]:
    if not words:
        return []

    sorted_words = sorted(words, key=lambda item: (item["start"], item["end"]))
    turns: list[TranscriptTurn] = []
    current_speaker = sorted_words[0]["speaker"]
    current_start = float(sorted_words[0]["start"])
    current_end = float(sorted_words[0]["end"])
    current_words = [str(sorted_words[0]["text"])]

    for word in sorted_words[1:]:
        speaker = str(word["speaker"])
        start = float(word["start"])
        end = float(word["end"])
        text = str(word["text"])

        if speaker == current_speaker and (start - current_end) <= turn_gap_seconds:
            current_words.append(text)
            current_end = max(current_end, end)
            continue

        turns.append(
            TranscriptTurn(
                speaker=current_speaker,
                start=current_start,
                end=current_end,
                text=" ".join(current_words).strip(),
            )
        )
        current_speaker = speaker
        current_start = start
        current_end = end
        current_words = [text]

    turns.append(
        TranscriptTurn(
            speaker=current_speaker,
            start=current_start,
            end=current_end,
            text=" ".join(current_words).strip(),
        )
    )
    return turns


def build_turns_by_speaker(
    words: list[dict[str, Any]],
    *,
    turn_gap_seconds: float = TURN_GAP_SECONDS,
) -> list[TranscriptTurn]:
    if not words:
        return []

    words_by_speaker: dict[str, list[dict[str, Any]]] = {}
    for word in words:
        speaker = str(word["speaker"])
        words_by_speaker.setdefault(speaker, []).append(word)

    turns: list[TranscriptTurn] = []
    for speaker_words in words_by_speaker.values():
        turns.extend(build_turns(speaker_words, turn_gap_seconds=turn_gap_seconds))

    return sorted(turns, key=lambda turn: (turn.start, turn.end, turn.speaker))


def is_noise_only_turn(turn: TranscriptTurn) -> bool:
    stripped = turn.text.strip()
    if not stripped:
        return True
    cleaned = re.sub(r"\[[^\]]+\]", "", stripped)
    return not cleaned.strip()


def strip_non_speech_markers(text: str) -> str:
    return re.sub(r"\[[^\]]+\]", " ", text)


def tokenize_turn_text(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", text.lower())


def normalize_turn_phrase(text: str) -> str:
    return " ".join(tokenize_turn_text(text))


def is_backchannel_text(text: str) -> bool:
    tokens = tokenize_turn_text(text)
    if not tokens:
        return False
    normalized = " ".join(tokens)
    return normalized in BACKCHANNEL_PHRASES or all(token in BACKCHANNEL_TOKENS for token in tokens)


def collapse_stutter_prefix(text: str) -> str:
    repeated_token_pattern = re.compile(
        r"^([A-Za-z0-9']+)(?:,\s*\1\b)+(?=(?:\s|[.?!,]|$))",
        flags=re.IGNORECASE,
    )
    while True:
        collapsed = repeated_token_pattern.sub(r"\1", text, count=1)
        if collapsed == text:
            return text
        text = collapsed.lstrip()


def remove_filler_lead_ins(text: str) -> str:
    cleaned = text
    filler_pattern = "|".join(
        sorted((re.escape(phrase) for phrase in FILLER_LEAD_IN_PHRASES), key=len, reverse=True)
    )
    lead_in_pattern = re.compile(
        rf"(^|(?<=[.?!])\s+|(?<=\.\.\.)\s+|(?<=--)\s+)"
        rf"(?:(?:{filler_pattern})(?:\s*,)?(?:\s+|$))+",
        flags=re.IGNORECASE,
    )
    while True:
        updated = lead_in_pattern.sub(r"\1", cleaned)
        if updated == cleaned:
            return cleaned
        cleaned = updated


def clean_turn_text(text: str) -> str:
    cleaned = strip_non_speech_markers(text).strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = remove_filler_lead_ins(cleaned)
    cleaned = collapse_stutter_prefix(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,")
    return cleaned.strip()


def collapse_repeated_tokens(text: str) -> str:
    repeated_token_pattern = re.compile(
        r"\b([A-Za-z0-9']{1,12})(?:,\s*|\s+)\1\b",
        flags=re.IGNORECASE,
    )
    while True:
        collapsed = repeated_token_pattern.sub(r"\1", text)
        if collapsed == text:
            return text
        text = collapsed


def remove_inline_fillers(text: str) -> str:
    filler_pattern = "|".join(
        sorted((re.escape(phrase) for phrase in FILLER_LEAD_IN_PHRASES), key=len, reverse=True)
    )
    cleaned = re.sub(
        rf"(?<=[,;:])\s*(?:{filler_pattern})\s+(?=[A-Za-z])",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    inline_word_pattern = "|".join(
        sorted((re.escape(word) for word in INLINE_FILLER_WORDS), key=len, reverse=True)
    )
    filler_sequence = rf"(?:{inline_word_pattern})(?:\s*,\s*(?:{inline_word_pattern}))*"
    cleaned = re.sub(
        rf",\s*{filler_sequence}\s*,\s*(?=(?:and|but|or)\b)",
        ", ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        rf",\s*{filler_sequence}\s*,\s*",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        rf"\s+{filler_sequence}\s+",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        rf"(?:(?<=^)|(?<=[\s,;:]))(?:{inline_word_pattern})(?:(?=[,;:])|(?=\s)|(?=$))",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r",\s*,", ", ", cleaned)
    cleaned = re.sub(r"\s+,", ",", cleaned)
    cleaned = re.sub(r",\s+([.!?])", r"\1", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def repair_text_after_cleanup(text: str) -> str:
    repaired = text.strip()
    if not repaired:
        return ""

    repaired = re.sub(r"\b([A-Za-z]{1,4})-\s+([A-Za-z][a-z]+)\b", r"\2", repaired)
    repaired = re.sub(r"\b([A-Za-z]{1,2})-([A-Za-z][a-z]+)\b", r"\2", repaired)
    repaired = remove_inline_fillers(repaired)
    repaired = collapse_repeated_tokens(repaired)
    repaired = re.sub(r"([,;:])(?=[A-Za-z])", r"\1 ", repaired)
    repaired = re.sub(r"([.!?])(?=[A-Za-z])", r"\1 ", repaired)
    repaired = re.sub(r"(?<=[a-z])(?=[A-Z][a-z])", " ", repaired)
    repaired = re.sub(r"\b(from|into|with|about|for|to)([A-Z]{2,})\b", r"\1 \2", repaired)
    repaired = re.sub(r"\s+", " ", repaired).strip()

    repaired = re.sub(
        r"(^|(?<=[.!?]\s))([a-z])",
        lambda match: match.group(1) + match.group(2).upper(),
        repaired,
    )
    repaired = re.sub(
        r'([.!?]["\']?\s+)([a-z])',
        lambda match: match.group(1) + match.group(2).upper(),
        repaired,
    )
    return repaired.strip(" ,")


def is_clause_repair_source_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.endswith(("...", "--", "-", ",", ":", ";")):
        return True
    if stripped.count('"') % 2 == 1:
        return True
    tokens = tokenize_turn_text(stripped)
    return len(tokens) <= 8 and bool(tokens and tokens[-1] in INCOMPLETE_ENDING_TOKENS)


def starts_with_continuation(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    stripped = stripped.lstrip("\"'([{")
    if not stripped:
        return False
    tokens = tokenize_turn_text(stripped)
    if not tokens:
        return False
    return stripped[0].islower() or tokens[0] in CLAUSE_CONTINUATION_STARTERS


def extract_leading_completion(text: str) -> tuple[str, str]:
    stripped = text.strip()
    if not stripped:
        return "", ""

    sentence_match = re.match(r'.*?[.!?]["\']?(?:\s+|$)', stripped)
    if sentence_match is not None:
        prefix = sentence_match.group(0).strip()
        if prefix and len(tokenize_turn_text(prefix)) <= 40:
            remainder = stripped[sentence_match.end() :].strip()
            return prefix, remainder

    if len(tokenize_turn_text(stripped)) <= 12:
        return stripped, ""
    return "", stripped


def repair_interrupted_same_speaker_turns(turns: list[TranscriptTurn]) -> list[TranscriptTurn]:
    if not turns:
        return []

    repaired_turns = list(turns)
    for index, turn in enumerate(repaired_turns):
        if not is_clause_repair_source_text(turn.text):
            continue

        same_speaker_seen = 0
        for next_index in range(index + 1, len(repaired_turns)):
            candidate = repaired_turns[next_index]
            if candidate.speaker == turn.speaker:
                same_speaker_seen += 1
            if same_speaker_seen > CLAUSE_REPAIR_MAX_INTERVENING_TURNS + 1:
                break
            if candidate.start - turn.end > CLAUSE_REPAIR_LOOKAHEAD_SECONDS:
                break
            if candidate.speaker != turn.speaker or not starts_with_continuation(candidate.text):
                continue
            if all(
                repaired_turns[between_index].speaker == turn.speaker
                for between_index in range(index + 1, next_index)
            ):
                continue

            prefix, remainder = extract_leading_completion(candidate.text)
            if not prefix:
                continue

            updated_text = repair_text_after_cleanup(f"{turn.text} {prefix}")
            repaired_turns[index] = replace(
                turn,
                text=updated_text,
                end=max(turn.end, candidate.end if not remainder else turn.end),
            )
            repaired_turns[next_index] = replace(
                candidate,
                text=repair_text_after_cleanup(remainder),
            )
            break

    return [turn for turn in repaired_turns if turn.text]


def finalize_turn_text(text: str) -> str:
    finalized = clean_turn_text(text)
    finalized = repair_text_after_cleanup(finalized)
    return finalized.strip()


def is_substantive_turn(turn: TranscriptTurn) -> bool:
    text = turn.text.strip()
    tokens = tokenize_turn_text(text)
    if not tokens:
        return False
    if text.endswith("?"):
        return True
    if len(tokens) >= SUBSTANTIVE_TURN_MIN_TOKENS:
        return True
    normalized = normalize_turn_phrase(text)
    if is_backchannel_text(text) or normalized in FRAGMENT_PHRASES:
        return False
    if normalized == normalize_turn_phrase(turn.speaker):
        return False
    if len(tokens) == 1 and tokens[0] in FRAGMENT_TOKENS:
        return False
    if len(tokens) <= DISPOSABLE_MICRO_TURN_MAX_TOKENS and tokens[-1] in FRAGMENT_TOKENS:
        return False
    return not ("..." in text or "--" in text)


def is_disposable_micro_turn(turn: TranscriptTurn) -> bool:
    text = turn.text.strip()
    tokens = tokenize_turn_text(text)
    if not tokens or len(tokens) > DISPOSABLE_MICRO_TURN_MAX_TOKENS or text.endswith("?"):
        return False

    normalized = normalize_turn_phrase(text)
    if is_backchannel_text(text):
        return True
    if normalized == normalize_turn_phrase(turn.speaker):
        return True
    if normalized in FRAGMENT_PHRASES:
        return True
    if len(tokens) == 1 and tokens[0] in FRAGMENT_TOKENS:
        return True
    if tokens[-1] in FRAGMENT_TOKENS:
        return True
    if len(tokens) <= 2 and tokens[0] in CLAUSE_CONTINUATION_STARTERS:
        return True
    return "..." in text or "--" in text


def drop_disposable_micro_turns(turns: list[TranscriptTurn]) -> list[TranscriptTurn]:
    if not turns:
        return []

    substantive_indices = [index for index, turn in enumerate(turns) if is_substantive_turn(turn)]
    kept_turns: list[TranscriptTurn] = []
    for index, turn in enumerate(turns):
        if not is_disposable_micro_turn(turn):
            kept_turns.append(turn)
            continue

        fully_overlapped = any(
            other_index != index
            and turns[other_index].speaker != turn.speaker
            and turns[other_index].start <= turn.start
            and turns[other_index].end >= turn.end
            for other_index in substantive_indices
        )
        same_speaker_future_substantive = any(
            turns[other_index].speaker == turn.speaker
            and turns[other_index].start >= turn.start
            and (turns[other_index].start - turn.end) <= SUBSTANTIVE_LOOKAHEAD_SECONDS
            for other_index in substantive_indices
        )
        if fully_overlapped or same_speaker_future_substantive:
            continue
        kept_turns.append(turn)
    return kept_turns


def merge_adjacent_same_speaker_turns(
    turns: list[TranscriptTurn],
    *,
    max_gap_seconds: float | None = None,
) -> list[TranscriptTurn]:
    if not turns:
        return []

    merged: list[TranscriptTurn] = [turns[0]]
    for turn in turns[1:]:
        previous = merged[-1]
        if previous.speaker != turn.speaker:
            merged.append(turn)
            continue
        gap = turn.start - previous.end
        if max_gap_seconds is not None and gap > max_gap_seconds:
            merged.append(turn)
            continue
        merged[-1] = TranscriptTurn(
            speaker=previous.speaker,
            start=previous.start,
            end=max(previous.end, turn.end),
            text=f"{previous.text} {turn.text}".strip(),
        )
    return merged


def format_timestamp(seconds: float) -> str:
    minutes = int(seconds // 60)
    remaining_seconds = seconds - (minutes * 60)
    return f"{minutes:02d}:{remaining_seconds:05.2f}"


def build_readable_turns(
    turns: list[TranscriptTurn],
    *,
    merge_same_speaker: bool,
) -> list[TranscriptTurn]:
    cleaned_turns = [
        TranscriptTurn(
            speaker=turn.speaker,
            start=turn.start,
            end=turn.end,
            text=clean_turn_text(turn.text),
        )
        for turn in turns
    ]
    filtered_turns = [turn for turn in cleaned_turns if turn.text and not is_noise_only_turn(turn)]
    readable_turns = repair_interrupted_same_speaker_turns(
        drop_disposable_micro_turns(filtered_turns)
    )
    if not readable_turns:
        return []

    if not merge_same_speaker:
        finalized_turns: list[TranscriptTurn] = []
        for turn in readable_turns:
            finalized_text = finalize_turn_text(turn.text)
            if not finalized_text:
                continue
            finalized_turns.append(replace(turn, text=finalized_text))
        return finalized_turns
    merged_turns = merge_adjacent_same_speaker_turns(
        readable_turns,
        max_gap_seconds=READABLE_MERGE_GAP_SECONDS,
    )
    finalized_turns: list[TranscriptTurn] = []
    for turn in merged_turns:
        finalized_text = finalize_turn_text(turn.text)
        if not finalized_text:
            continue
        finalized_turns.append(replace(turn, text=finalized_text))
    return finalized_turns


def build_single_file_turns(payload: dict[str, Any]) -> tuple[list[TranscriptTurn], list[str]]:
    words = payload.get("words") or []
    label_map: dict[str, str] = {}
    for word in words:
        speaker_id = str(word.get("speaker_id", "speaker_0"))
        if speaker_id not in label_map:
            label_map[speaker_id] = f"Speaker {len(label_map) + 1}"

    speaker_count = len(label_map) or 1
    turn_gap_seconds = SINGLE_SPEAKER_TURN_GAP_SECONDS if speaker_count == 1 else TURN_GAP_SECONDS
    turns = build_turns(normalize_word_entries(words, label_map), turn_gap_seconds=turn_gap_seconds)
    readable_turns = build_readable_turns(turns, merge_same_speaker=speaker_count > 1)
    return readable_turns, list(label_map.values())


def build_multi_file_turns(
    payload: dict[str, Any],
    audio_files: list[Path],
) -> tuple[list[TranscriptTurn], list[str]]:
    label_map = {
        f"speaker_{index}": sanitize_speaker_name(audio_file, index + 1)
        for index, audio_file in enumerate(audio_files)
    }
    speaker_labels = [label_map[f"speaker_{index}"] for index in range(len(audio_files))]

    words: list[dict[str, Any]] = []
    transcripts = payload.get("transcripts") or []
    for transcript in transcripts:
        channel_index = int(transcript.get("channel_index", 0))
        speaker_id = f"speaker_{channel_index}"
        for word in transcript.get("words") or []:
            normalized_word = dict(word)
            normalized_word.setdefault("speaker_id", speaker_id)
            words.append(normalized_word)

    turns = build_turns_by_speaker(normalize_word_entries(words, label_map))
    return build_readable_turns(turns, merge_same_speaker=True), speaker_labels


def require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise TranscriptCliError(
            "ffmpeg is required for multi-file transcription. Install ffmpeg and try again.",
            exit_code=3,
        )


def merge_to_multichannel(audio_files: list[Path], output_path: Path) -> Path:
    if len(audio_files) < 2:
        raise TranscriptCliError("Multichannel merging requires at least two files.", exit_code=2)

    require_ffmpeg()
    layout = MULTICHANNEL_LAYOUTS[len(audio_files)]
    input_refs = "".join(f"[a{index}]" for index in range(len(audio_files)))
    filter_parts = [
        f"[{index}:a]pan=mono|c0=c0,aresample=16000[a{index}]" for index in range(len(audio_files))
    ]
    filter_parts.append(f"{input_refs}join=inputs={len(audio_files)}:channel_layout={layout}[out]")
    filter_complex = ";".join(filter_parts)

    command = ["ffmpeg", "-y"]
    for audio_file in audio_files:
        command.extend(["-i", str(audio_file)])
    command.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            "-ac",
            str(len(audio_files)),
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
    )

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or "ffmpeg failed without stderr output."
        raise TranscriptCliError(f"merge failed: {stderr}", exit_code=3) from exc

    return output_path


def transcribe_single_file(
    audio_file: Path,
    api_key: str,
    *,
    reporter: Reporter | None = None,
) -> dict[str, Any]:
    client = create_client(api_key)
    if reporter is not None:
        reporter(
            "transcription",
            "Uploading audio to ElevenLabs and starting diarized transcription",
        )
        reporter("wait", "Waiting on ElevenLabs")

    def perform_request() -> dict[str, Any]:
        try:
            with audio_file.open("rb") as handle:
                response = client.speech_to_text.convert(
                    file=handle,
                    model_id=DEFAULT_MODEL_ID,
                    diarize=True,
                    timestamps_granularity="word",
                )
        except Exception as exc:  # noqa: BLE001
            raise TranscriptCliError(f"transcription request failed: {exc}", exit_code=4) from exc
        return cast(dict[str, Any], to_jsonable(response))

    return _run_with_heartbeat(perform_request, reporter=reporter)


def transcribe_multi_file(
    audio_file: Path,
    api_key: str,
    *,
    reporter: Reporter | None = None,
) -> dict[str, Any]:
    client = create_client(api_key)
    if reporter is not None:
        reporter(
            "transcription",
            "Uploading multichannel audio to ElevenLabs and starting transcription",
        )
        reporter("wait", "Waiting on ElevenLabs")

    def perform_request() -> dict[str, Any]:
        try:
            with audio_file.open("rb") as handle:
                response = client.speech_to_text.convert(
                    file=handle,
                    model_id=DEFAULT_MODEL_ID,
                    use_multi_channel=True,
                    diarize=False,
                    timestamps_granularity="word",
                )
        except Exception as exc:  # noqa: BLE001
            raise TranscriptCliError(f"transcription request failed: {exc}", exit_code=4) from exc
        return cast(dict[str, Any], to_jsonable(response))

    return _run_with_heartbeat(perform_request, reporter=reporter)


def run_transcription(
    audio_files: list[Path],
    *,
    output_dir: Path,
    api_key: str | None = None,
    force: bool = False,
    keep_merged_audio: bool = False,
    reporter: Reporter | None = None,
) -> TranscriptRunResult:
    started_at = time.monotonic()
    if reporter is not None:
        reporter("preflight", "Validating inputs and configuration")

    try:
        resolved_files = validate_audio_files(audio_files)
        resolved_api_key = resolve_api_key(api_key)
        raw_path, conversation_path, persisted_merged_path = ensure_output_paths(
            output_dir,
            force=force,
            keep_merged_audio=keep_merged_audio,
        )
    except TranscriptCliError as exc:
        raise TranscriptCliError(
            f"validation failed: {exc.message}",
            exit_code=exc.exit_code,
        ) from exc

    merged_temp_path: Path | None = None
    payload: dict[str, Any]
    speaker_labels = detect_speaker_labels(resolved_files)
    transcription_id: str | None
    mode = detect_mode(resolved_files)
    if reporter is not None:
        reporter("mode", f"Mode: {mode}")

    try:
        if len(resolved_files) == 1:
            payload = transcribe_single_file(
                resolved_files[0],
                resolved_api_key,
                reporter=reporter,
            )
            turns, speaker_labels = build_single_file_turns(payload)
        else:
            if persisted_merged_path is not None:
                merged_temp_path = persisted_merged_path
            else:
                with tempfile.NamedTemporaryFile(
                    prefix="multichannel_",
                    suffix=".wav",
                    dir=output_dir,
                    delete=False,
                ) as temp_file:
                    merged_temp_path = Path(temp_file.name)

            if reporter is not None:
                reporter("merge", "Merging speaker tracks into a multichannel WAV")
            merge_to_multichannel(resolved_files, merged_temp_path)
            if reporter is not None:
                reporter("merge", "Multichannel merge complete")
            payload = transcribe_multi_file(
                merged_temp_path,
                resolved_api_key,
                reporter=reporter,
            )
            turns, speaker_labels = build_multi_file_turns(payload, resolved_files)
    finally:
        if not keep_merged_audio and merged_temp_path is not None and merged_temp_path.exists():
            merged_temp_path.unlink()

    try:
        if reporter is not None:
            reporter("write", "Writing transcript artifacts")
        write_json(raw_path, payload)
        write_conversation(conversation_path, turns)
    except OSError as exc:
        raise TranscriptCliError(f"output write failed: {exc}", exit_code=5) from exc

    transcription_id = (
        str(payload.get("transcription_id")) if payload.get("transcription_id") else None
    )

    return TranscriptRunResult(
        mode=mode,
        raw_path=raw_path,
        conversation_path=conversation_path,
        merged_audio_path=persisted_merged_path,
        speaker_labels=speaker_labels,
        transcription_id=transcription_id,
        elapsed_seconds=time.monotonic() - started_at,
    )

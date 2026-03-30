"""Core transcription workflow for the transcript CLI."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from elevenlabs import ElevenLabs

RAW_TRANSCRIPT_FILENAME = "transcript_raw.json"
CONVERSATION_TRANSCRIPT_FILENAME = "transcript_conversation.txt"
MERGED_AUDIO_FILENAME = "multichannel_input.wav"
DEFAULT_MODEL_ID = "scribe_v2"
TURN_GAP_SECONDS = 0.7
MULTICHANNEL_LAYOUTS = {
    2: "stereo",
    3: "3.0",
    4: "4.0",
    5: "5.0",
}


class TranscriptCliError(Exception):
    """A user-facing error with a deterministic exit code."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


@dataclass(slots=True)
class TranscriptTurn:
    speaker: str
    text: str


@dataclass(slots=True)
class TranscriptRunResult:
    mode: str
    raw_path: Path
    conversation_path: Path
    merged_audio_path: Path | None
    speaker_labels: list[str]
    transcription_id: str | None

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
    rendered = "\n\n".join(f"{turn.speaker}: {turn.text}" for turn in turns)
    path.write_text(rendered + "\n", encoding="utf-8")


def sanitize_speaker_name(path: Path, index: int) -> str:
    cleaned = re.sub(r"[_-]+", " ", path.stem)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return f"Speaker {index}"
    return " ".join(part.capitalize() for part in cleaned.split(" "))


def normalize_word_entries(
    words: list[dict[str, Any]],
    label_map: dict[str, str],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for word in words:
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

        turns.append(TranscriptTurn(speaker=current_speaker, text=" ".join(current_words).strip()))
        current_speaker = speaker
        current_end = end
        current_words = [text]

    turns.append(TranscriptTurn(speaker=current_speaker, text=" ".join(current_words).strip()))
    return turns


def build_single_file_turns(payload: dict[str, Any]) -> tuple[list[TranscriptTurn], list[str]]:
    words = payload.get("words") or []
    label_map: dict[str, str] = {}
    for word in words:
        speaker_id = str(word.get("speaker_id", "speaker_0"))
        if speaker_id not in label_map:
            label_map[speaker_id] = f"Speaker {len(label_map) + 1}"

    turns = build_turns(normalize_word_entries(words, label_map))
    return turns, list(label_map.values())


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

    turns = build_turns(normalize_word_entries(words, label_map))
    return turns, speaker_labels


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
        raise TranscriptCliError(
            f"Failed to merge audio into multichannel WAV: {stderr}",
            exit_code=3,
        ) from exc

    return output_path


def transcribe_single_file(audio_file: Path, api_key: str) -> dict[str, Any]:
    client = create_client(api_key)
    try:
        with audio_file.open("rb") as handle:
            response = client.speech_to_text.convert(
                file=handle,
                model_id=DEFAULT_MODEL_ID,
                diarize=True,
                timestamps_granularity="word",
            )
    except Exception as exc:  # noqa: BLE001
        raise TranscriptCliError(f"ElevenLabs transcription failed: {exc}", exit_code=4) from exc
    return cast(dict[str, Any], to_jsonable(response))


def transcribe_multi_file(audio_file: Path, api_key: str) -> dict[str, Any]:
    client = create_client(api_key)
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
        raise TranscriptCliError(f"ElevenLabs transcription failed: {exc}", exit_code=4) from exc
    return cast(dict[str, Any], to_jsonable(response))


def run_transcription(
    audio_files: list[Path],
    *,
    output_dir: Path,
    api_key: str | None = None,
    force: bool = False,
    keep_merged_audio: bool = False,
) -> TranscriptRunResult:
    resolved_files = validate_audio_files(audio_files)
    resolved_api_key = resolve_api_key(api_key)
    raw_path, conversation_path, persisted_merged_path = ensure_output_paths(
        output_dir,
        force=force,
        keep_merged_audio=keep_merged_audio,
    )

    merged_temp_path: Path | None = None
    payload: dict[str, Any]
    speaker_labels: list[str]
    transcription_id: str | None
    mode = "diarized" if len(resolved_files) == 1 else "multichannel"

    try:
        if len(resolved_files) == 1:
            payload = transcribe_single_file(resolved_files[0], resolved_api_key)
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

            merge_to_multichannel(resolved_files, merged_temp_path)
            payload = transcribe_multi_file(merged_temp_path, resolved_api_key)
            turns, speaker_labels = build_multi_file_turns(payload, resolved_files)
    finally:
        if not keep_merged_audio and merged_temp_path is not None and merged_temp_path.exists():
            merged_temp_path.unlink()

    write_json(raw_path, payload)
    write_conversation(conversation_path, turns)
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
    )

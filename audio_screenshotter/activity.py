"""Detect audio activity (speech vs. silence) in a recording using ffmpeg's
silencedetect filter, and derive the timestamps where speech starts.
"""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Segment:
    start: float
    end: float


def extract_audio(video_path: Path, audio_path: Path) -> Path:
    """Pull the audio track out as mono 16kHz WAV, suitable for both
    silence detection and transcription."""
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000",
        str(audio_path),
    ]
    subprocess.run(cmd, check=True)
    return audio_path


def detect_speech_segments(
    audio_path: Path,
    noise_threshold_db: float = -30.0,
    min_silence_duration: float = 0.6,
) -> list:
    """Run ffmpeg's silencedetect filter and invert the reported silences
    into a list of speech Segments covering the rest of the timeline.
    """
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats",
        "-i", str(audio_path),
        "-af", f"silencedetect=noise={noise_threshold_db}dB:d={min_silence_duration}",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    log = result.stderr

    silence_start_re = re.compile(r"silence_start:\s*([\d.]+)")
    silence_end_re = re.compile(r"silence_end:\s*([\d.]+)")

    duration = _probe_duration(audio_path)

    silences = []
    pending_start = None
    for line in log.splitlines():
        start_match = silence_start_re.search(line)
        if start_match:
            pending_start = float(start_match.group(1))
            continue
        end_match = silence_end_re.search(line)
        if end_match and pending_start is not None:
            silences.append((pending_start, float(end_match.group(1))))
            pending_start = None
    if pending_start is not None:
        silences.append((pending_start, duration))

    # Invert silences over [0, duration] to get speech segments.
    speech_segments = []
    cursor = 0.0
    for silence_start, silence_end in silences:
        if silence_start > cursor:
            speech_segments.append(Segment(start=cursor, end=silence_start))
        cursor = max(cursor, silence_end)
    if cursor < duration:
        speech_segments.append(Segment(start=cursor, end=duration))

    return [s for s in speech_segments if s.end - s.start > 0.1]


def _probe_duration(media_path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())

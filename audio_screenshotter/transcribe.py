"""Transcribe audio via Mistral's Voxtral speech-to-text API."""

import os
from pathlib import Path

import requests

MISTRAL_TRANSCRIPTION_URL = "https://api.mistral.ai/v1/audio/transcriptions"
DEFAULT_MODEL = "voxtral-mini-latest"


class TranscriptionError(RuntimeError):
    pass


def transcribe_audio(audio_path: Path, api_key: str = None, model: str = DEFAULT_MODEL) -> dict:
    """Send the audio file to Mistral and return the parsed JSON response,
    requesting segment-level timestamps so output can be correlated with
    screenshots later.
    """
    api_key = api_key or os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise TranscriptionError(
            "MISTRAL_API_KEY is not set. Add it to a .env file in the project root."
        )

    with open(audio_path, "rb") as f:
        files = {"file": (audio_path.name, f, "audio/wav")}
        data = {
            "model": model,
            "timestamp_granularities[]": "segment",
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        response = requests.post(
            MISTRAL_TRANSCRIPTION_URL,
            headers=headers,
            data=data,
            files=files,
            timeout=600,
        )

    if response.status_code != 200:
        raise TranscriptionError(
            f"Mistral transcription failed ({response.status_code}): {response.text}"
        )

    return response.json()


def extract_segments(transcription_response: dict) -> list:
    """Normalize the response's segments to a plain list of
    {start, end, text} dicts, tolerating minor shape differences."""
    segments = transcription_response.get("segments")
    if not segments:
        # Fall back to treating the whole transcript as one segment.
        return [{
            "start": 0.0,
            "end": transcription_response.get("duration", 0.0),
            "text": transcription_response.get("text", ""),
        }]

    normalized = []
    for seg in segments:
        normalized.append({
            "start": seg.get("start", 0.0),
            "end": seg.get("end", 0.0),
            "text": seg.get("text", "").strip(),
        })
    return normalized

"""Remember the last avfoundation device indices that worked, so `record`
and `run` don't need --video-device/--audio-device on every invocation.
"""

import json
from pathlib import Path

CACHE_PATH = Path(".audio_screenshotter_devices.json")

DEFAULT_VIDEO_DEVICE = "1"
DEFAULT_AUDIO_DEVICE = "0"


def load() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save(video_device: str, audio_device: str) -> None:
    CACHE_PATH.write_text(json.dumps({
        "video_device": video_device,
        "audio_device": audio_device,
    }, indent=2))


def resolve(video_device: str = None, audio_device: str = None) -> tuple:
    """Resolve device indices: an explicit CLI argument wins, then the
    cached value from a previous run, then a hardcoded fallback. Whatever
    is resolved is written back to the cache for next time.
    """
    cache = load()
    resolved_video = video_device or cache.get("video_device") or DEFAULT_VIDEO_DEVICE
    resolved_audio = audio_device or cache.get("audio_device") or DEFAULT_AUDIO_DEVICE
    save(resolved_video, resolved_audio)
    return resolved_video, resolved_audio

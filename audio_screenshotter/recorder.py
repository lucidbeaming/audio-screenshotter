"""Simultaneous screen + microphone recording via ffmpeg (macOS/avfoundation).

Stopping is done from the keyboard by pressing 'q' in the terminal running
this process. ffmpeg reads that keystroke from its own stdin and shuts the
recording down cleanly (finalizing the container), which is why this module
runs ffmpeg with an inherited, interactive stdin instead of Popen+CTRL-C.
"""

import subprocess
from pathlib import Path


def build_record_command(
    output_path: Path,
    video_device: str,
    audio_device: str,
    framerate: int = 30,
    video_bitrate_preset: str = "ultrafast",
) -> list:
    """Build the ffmpeg command that records screen video + mic audio together.

    avfoundation lets one -i take a combined "video:audio" device index pair,
    so a single input captures both, keeping the two streams sample-aligned
    in one output container.
    """
    input_spec = f"{video_device}:{audio_device}"
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "info",
        "-f", "avfoundation",
        "-framerate", str(framerate),
        "-i", input_spec,
        "-c:v", "libx264",
        "-preset", video_bitrate_preset,
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_path),
    ]


def record(
    output_path: Path,
    video_device: str,
    audio_device: str,
    framerate: int = 30,
) -> None:
    """Run ffmpeg interactively; the user stops it by pressing 'q'."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_record_command(output_path, video_device, audio_device, framerate)

    print("Recording screen + microphone.")
    print("Press 'q' in this terminal to stop the recording (do not use Ctrl-C).")
    print(f"Command: {' '.join(cmd)}")

    # Inherit stdin/stdout/stderr so ffmpeg can read the 'q' keypress and the
    # user can see its live progress output.
    subprocess.run(cmd)

    if not output_path.exists():
        raise RuntimeError(f"Recording did not produce an output file at {output_path}")
    print(f"Saved recording to {output_path}")

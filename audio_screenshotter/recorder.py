"""Simultaneous screen + microphone recording via ffmpeg (macOS/avfoundation).

Controlled entirely from the keyboard while recording:
  q  stop recording (finalizes the file, then the caller can process it)
  p  pause / resume

ffmpeg has no native pause, so pausing is implemented by sending SIGSTOP to
the ffmpeg process (freezing it completely, capturing nothing) and SIGCONT
to resume. Stopping is done by writing 'q' to ffmpeg's own stdin, which is
how ffmpeg shuts itself down cleanly and finalizes the output container
(the same as pressing 'q' in a normal interactive ffmpeg session, but
forwarded programmatically since we take over stdin to read single
keypresses without waiting for Enter).
"""

import os
import select
import signal
import subprocess
import sys
import termios
import tty
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


class _RawStdin:
    """Put stdin into cbreak mode so single keypresses (q/p) are readable
    without waiting for Enter, restoring the original terminal settings
    afterwards no matter how the block exits."""

    def __enter__(self):
        self.fd = sys.stdin.fileno()
        self.old_settings = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        return self

    def __exit__(self, *exc_info):
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)


def _listen_for_keys(proc: subprocess.Popen) -> None:
    paused = False
    with _RawStdin():
        while proc.poll() is None:
            ready, _, _ = select.select([sys.stdin], [], [], 0.2)
            if not ready:
                continue
            ch = sys.stdin.read(1)

            if ch == "q":
                if paused:
                    os.kill(proc.pid, signal.SIGCONT)
                    paused = False
                if proc.stdin:
                    try:
                        proc.stdin.write(b"q")
                        proc.stdin.flush()
                    except BrokenPipeError:
                        pass
                break

            elif ch == "p":
                if paused:
                    os.kill(proc.pid, signal.SIGCONT)
                    paused = False
                    print("\nResumed. Press 'p' to pause, 'q' to stop.")
                else:
                    os.kill(proc.pid, signal.SIGSTOP)
                    paused = True
                    print("\nPaused. Press 'p' to resume, 'q' to stop.")


def record(
    output_path: Path,
    video_device: str,
    audio_device: str,
    framerate: int = 30,
) -> None:
    """Record until the user presses 'q'. Pause/resume with 'p'."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_record_command(output_path, video_device, audio_device, framerate)

    print("Recording screen + microphone.")
    print("Press 'p' to pause/resume, 'q' to stop.")
    print(f"Command: {' '.join(cmd)}")

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        _listen_for_keys(proc)
    finally:
        proc.wait()

    if not output_path.exists():
        raise RuntimeError(f"Recording did not produce an output file at {output_path}")
    print(f"Saved recording to {output_path}")

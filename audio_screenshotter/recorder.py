"""Simultaneous screen + microphone recording via ffmpeg (macOS/avfoundation),
optionally with system audio (see system_audio.py) as a second audio track.

Controlled entirely from the keyboard while recording:
  q  stop recording (finalizes the file, then the caller can process it)
  p  pause / resume

ffmpeg has no native pause, so pausing is implemented by sending SIGSTOP to
the ffmpeg process (freezing it completely, capturing nothing) and SIGCONT
to resume; the system audio helper, if running, is paused the same way.
Stopping is done by writing 'q' to ffmpeg's own stdin, which is
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

from audio_screenshotter import system_audio


MAX_WIDTH = 1920
MAX_HEIGHT = 1080


def build_record_command(
    output_path: Path,
    video_device: str,
    audio_device: str,
    framerate: int = 15,
    video_bitrate_preset: str = "ultrafast",
) -> list:
    """Build the ffmpeg command that records screen video + mic audio together.

    avfoundation lets one -i take a combined "video:audio" device index pair,
    so a single input captures both, keeping the two streams sample-aligned
    in one output container.

    -r after -i forces a constant output frame rate; avfoundation otherwise
    reports an unreliable input timebase that ffmpeg carries straight into
    the mov container, producing files QuickTime/Preview can't open. The
    scale filter caps capture at 1080p (downscaling only, never upscaling)
    since screen recordings are for screenshots/transcription, not full-res
    playback, and keeps dimensions even as libx264/yuv420p requires.

    -pixel_format uyvy422 before -i requests a format the screen input
    actually supports, skipping ffmpeg's default-then-retry negotiation
    (which otherwise logs "Selected pixel format (yuv420p) is not
    supported..." and overrides it to uyvy422 anyway). This does NOT
    suppress AVFoundation's separate "Configuration of video device
    failed, falling back to default" warning -- that one is logged
    unconditionally for AVCaptureScreenInput regardless of any option
    passed here (verified: it appears even with zero avfoundation options
    set), since ffmpeg's device-locking/activeFormat negotiation path
    doesn't apply to screen-capture inputs. It's cosmetic; output still
    ends up at the requested framerate/resolution via -r/-vf below.
    The final -pix_fmt yuv420p (an output option) still converts to what
    libx264 needs during encode.
    """
    input_spec = f"{video_device}:{audio_device}"
    scale = (
        f"scale='min({MAX_WIDTH},iw)':'min({MAX_HEIGHT},ih)'"
        ":force_original_aspect_ratio=decrease:force_divisible_by=2"
    )
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "info",
        "-f", "avfoundation",
        "-pixel_format", "uyvy422",
        "-framerate", str(framerate),
        "-i", input_spec,
        "-r", str(framerate),
        "-vf", scale,
        "-c:v", "libx264",
        "-preset", video_bitrate_preset,
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-metadata", "encoding_tool=audio-screenshotter",
        "-metadata", f"comment=framerate={framerate}fps, max {MAX_WIDTH}x{MAX_HEIGHT}, "
                     f"video_device={video_device}, audio_device={audio_device}",
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


def _listen_for_keys(proc: subprocess.Popen, system=None) -> None:
    paused = False

    def set_paused(pause: bool) -> None:
        nonlocal paused
        os.kill(proc.pid, signal.SIGSTOP if pause else signal.SIGCONT)
        if system and pause:
            system.pause()
        elif system:
            system.resume()
        paused = pause

    with _RawStdin():
        while proc.poll() is None:
            ready, _, _ = select.select([sys.stdin], [], [], 0.2)
            if not ready:
                continue
            ch = sys.stdin.read(1)

            if ch == "q":
                if paused:
                    set_paused(False)
                if proc.stdin:
                    try:
                        proc.stdin.write(b"q")
                        proc.stdin.flush()
                    except BrokenPipeError:
                        pass
                print("\nStopping, finalizing recording...")
                break

            elif ch == "p":
                if paused:
                    set_paused(False)
                    print("\nResumed. Press 'p' to pause, 'q' to stop.")
                else:
                    set_paused(True)
                    print("\nPaused. Press 'p' to resume, 'q' to stop.")


def record(
    output_path: Path,
    video_device: str,
    audio_device: str,
    framerate: int = 15,
    capture_system_audio: bool = True,
) -> None:
    """Record until the user presses 'q'. Pause/resume with 'p'.

    With capture_system_audio, the Mac's audio output is recorded alongside
    and added to the video as a second audio track once recording stops.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_record_command(output_path, video_device, audio_device, framerate)
    log_path = output_path.with_suffix(".log")
    system_wav = output_path.with_name(output_path.stem + ".system.wav")

    system = None
    if capture_system_audio:
        system = system_audio.SystemAudioCapture(system_wav)
        system.start()
        system.wait_until_capturing()

    sources = "screen + microphone + system audio" if system else "screen + microphone"
    print(f"Recording {sources}.")
    print("Press 'p' to pause/resume, 'q' to stop.")

    with open(log_path, "w") as log_file:
        log_file.write(f"Command: {' '.join(cmd)}\n\n")
        log_file.flush()
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=log_file, stderr=subprocess.STDOUT)
        try:
            _listen_for_keys(proc, system)
        finally:
            proc.wait()
            if system:
                system.stop()

    if not output_path.exists():
        tail = "\n".join(log_path.read_text().splitlines()[-20:])
        raise RuntimeError(
            f"Recording did not produce an output file at {output_path}\n"
            f"ffmpeg log ({log_path}), last 20 lines:\n{tail}"
        )

    if system:
        offset = system.first_pts - system_audio.ffmpeg_input_start(log_path.read_text())
        system_audio.add_system_track(output_path, system_wav, offset)
        system_wav.unlink()

    log_path.unlink()
    print(f"Saved recording to {output_path}")

"""Record system audio (everything the Mac plays, e.g. VoiceOver speech)
alongside the screen + mic recording, then add it to the video as a second
audio track.

ffmpeg's avfoundation input can't capture system output without a virtual
audio driver, so this runs a small ScreenCaptureKit helper
(swift/system_audio_capture.swift), compiled on first use with swiftc.

Lining the tracks up: both ffmpeg's avfoundation input and ScreenCaptureKit
timestamp samples on the host clock. ffmpeg logs its input's "start:" time
and the helper prints the timestamp of its first buffer, so the difference is
how far the system track starts after (or before) the video.
"""

import re
import shutil
import signal
import subprocess
import threading
from pathlib import Path

PACKAGE_DIR = Path(__file__).parent
SOURCE_PATH = PACKAGE_DIR / "swift" / "system_audio_capture.swift"
BINARY_PATH = PACKAGE_DIR / "swift" / "build" / "system-audio-capture"

MIC_TRACK_TITLE = "Microphone"
SYSTEM_TRACK_TITLE = "System audio"


class SystemAudioError(RuntimeError):
    pass


def ensure_helper() -> Path:
    """Compile the helper if it's missing or older than its source."""
    if BINARY_PATH.exists() and BINARY_PATH.stat().st_mtime >= SOURCE_PATH.stat().st_mtime:
        return BINARY_PATH
    if not shutil.which("swiftc"):
        raise SystemAudioError(
            "swiftc not found; install the Xcode command line tools "
            "(xcode-select --install) or pass --no-system-audio."
        )
    BINARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    print("Building the system audio helper (first run only)...")
    result = subprocess.run(
        ["swiftc", "-O", "-o", str(BINARY_PATH), str(SOURCE_PATH)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SystemAudioError(f"Could not build the system audio helper:\n{result.stderr}")
    return BINARY_PATH


class SystemAudioCapture:
    """Runs the helper as a child process for the length of a recording."""

    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.first_pts = None
        self._first_pts_seen = threading.Event()
        self.proc = None

    def start(self) -> None:
        helper = ensure_helper()
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            [str(helper), str(self.output_path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()

    def _read_stdout(self) -> None:
        for line in self.proc.stdout:
            if line.startswith("first_pts="):
                self.first_pts = float(line.split("=", 1)[1])
                self._first_pts_seen.set()

    def wait_until_capturing(self, timeout: float = 10.0) -> None:
        """Block until the first buffer arrives, so recording starts with
        system audio already flowing (and a permission or startup failure
        is reported before the user starts talking)."""
        if not self._first_pts_seen.wait(timeout):
            self.stop()
            raise SystemAudioError(
                f"System audio capture didn't start within {timeout:.0f}s.\n{self._stderr()}\n"
                "Check Screen Recording permission for this terminal, or pass --no-system-audio."
            )

    def pause(self) -> None:
        self.proc.send_signal(signal.SIGSTOP)

    def resume(self) -> None:
        self.proc.send_signal(signal.SIGCONT)

    def stop(self) -> None:
        """Ask the helper to finish writing and wait for it to exit."""
        if self.proc.poll() is not None:
            return
        self.proc.send_signal(signal.SIGCONT)
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            self.proc.wait(timeout=5)

    def _stderr(self) -> str:
        if self.proc.poll() is None:
            return ""
        return self.proc.stderr.read().strip()


def ffmpeg_input_start(log_text: str) -> float:
    """The host-clock start time ffmpeg logged for the avfoundation input."""
    match = re.search(r"Input #0, avfoundation.*?\n\s*Duration: .*?start: ([\d.]+)", log_text, re.S)
    if not match:
        raise SystemAudioError("Couldn't find the avfoundation input's start time in ffmpeg's log.")
    return float(match.group(1))


def add_system_track(video_path: Path, system_audio_path: Path, offset: float) -> None:
    """Rewrite video_path with system_audio_path added as a second audio
    track, shifted by `offset` seconds (positive: it started after the video)
    so both tracks start at 0 and stay in step. Video and mic are copied, not
    re-encoded."""
    if offset >= 0:
        align = f"adelay=delays={round(offset * 1000)}:all=1"
    else:
        align = f"atrim=start={-offset:.6f},asetpts=PTS-STARTPTS"
    tmp_path = video_path.with_name(video_path.stem + ".muxing" + video_path.suffix)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_path),
        "-i", str(system_audio_path),
        "-filter_complex", f"[1:a]{align}[system]",
        "-map", "0:v", "-map", "0:a", "-map", "[system]",
        "-c:v", "copy", "-c:a:0", "copy", "-c:a:1", "aac", "-b:a:1", "192k",
        # The mov muxer stores a track's name as its handler name, not "title".
        "-metadata:s:a:0", f"handler_name={MIC_TRACK_TITLE}",
        "-metadata:s:a:1", f"handler_name={SYSTEM_TRACK_TITLE}",
        str(tmp_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tmp_path.unlink(missing_ok=True)
        raise SystemAudioError(f"Couldn't add the system audio track:\n{result.stderr}")
    tmp_path.replace(video_path)

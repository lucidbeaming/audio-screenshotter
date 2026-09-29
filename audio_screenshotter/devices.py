"""List capture devices available to ffmpeg's avfoundation input (macOS)."""

import subprocess


def list_avfoundation_devices() -> str:
    """Return ffmpeg's avfoundation device listing as text.

    ffmpeg prints the device list to stderr and then exits non-zero because
    no actual capture was requested, so we always read stderr regardless of
    the return code.
    """
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True,
        text=True,
    )
    return result.stderr

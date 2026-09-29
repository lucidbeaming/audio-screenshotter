"""Extract still frames from the recorded video at given timestamps."""

import subprocess
from pathlib import Path


def extract_frame(video_path: Path, timestamp: float, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{timestamp:.3f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)
    return out_path


def extract_frames_for_segments(video_path: Path, segments, outdir: Path, lead_in: float = 0.3):
    """Take one screenshot per speech segment, offset slightly after the
    segment start so the on-screen action has begun (lead_in seconds).
    """
    outdir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, segment in enumerate(segments):
        timestamp = min(segment.start + lead_in, segment.end)
        out_path = outdir / f"screenshot_{i:04d}.png"
        extract_frame(video_path, timestamp, out_path)
        results.append({"file": str(out_path), "timestamp": timestamp,
                         "segment_start": segment.start, "segment_end": segment.end})
    return results

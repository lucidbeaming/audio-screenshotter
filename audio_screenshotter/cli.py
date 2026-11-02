"""Command-line entry point.

Subcommands:
  devices   list avfoundation capture devices (to pick video/audio indices)
  record    record screen + mic (+ system audio as a second track) to a video
            file (press 'q' to stop, 'p' to pause)
  analyze   detect speech activity, extract screenshots, transcribe, and
            write a correlated JSON report for an existing recording
  run       record, then analyze, in one go
"""

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from audio_screenshotter import activity, correlate, device_cache, devices, recorder, screenshots, transcribe

RECORDINGS_DIR = Path("recordings")
OUTPUT_DIR = Path("output")


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def cmd_devices(_args):
    print(devices.list_avfoundation_devices())


def cmd_record(args):
    output_path = Path(args.output) if args.output else RECORDINGS_DIR / f"recording_{timestamp()}.mov"
    video_device, audio_device = device_cache.resolve(args.video_device, args.audio_device)
    print(f"Using video device {video_device}, audio device {audio_device}")
    recorder.record(
        output_path=output_path,
        video_device=video_device,
        audio_device=audio_device,
        framerate=args.framerate,
        capture_system_audio=not args.no_system_audio,
    )


def cmd_analyze(args):
    outdir = Path(args.outdir) if args.outdir else OUTPUT_DIR / Path(args.video).stem
    analyze_recording(
        video_path=Path(args.video),
        outdir=outdir,
        noise_threshold_db=args.noise_threshold,
        min_silence_duration=args.min_silence,
        lead_in=args.lead_in,
    )


def cmd_run(args):
    ts = timestamp()
    output_path = Path(args.output) if args.output else RECORDINGS_DIR / f"recording_{ts}.mov"
    video_device, audio_device = device_cache.resolve(args.video_device, args.audio_device)
    print(f"Using video device {video_device}, audio device {audio_device}")
    recorder.record(
        output_path=output_path,
        video_device=video_device,
        audio_device=audio_device,
        framerate=args.framerate,
        capture_system_audio=not args.no_system_audio,
    )
    print("Recording stopped, processing...")
    outdir = Path(args.outdir) if args.outdir else OUTPUT_DIR / output_path.stem
    analyze_recording(
        video_path=output_path,
        outdir=outdir,
        noise_threshold_db=args.noise_threshold,
        min_silence_duration=args.min_silence,
        lead_in=args.lead_in,
    )


# Audio tracks in a recording, in order: what the narrator said into the
# mic, then (when recorded) what the Mac itself played, e.g. VoiceOver.
SOURCES = [
    {"source": "mic", "wav": "audio.wav", "screenshot_prefix": "screenshot"},
    {"source": "system", "wav": "system_audio.wav", "screenshot_prefix": "system"},
]


def analyze_recording(video_path: Path, outdir: Path, noise_threshold_db: float,
                       min_silence_duration: float, lead_in: float):
    outdir.mkdir(parents=True, exist_ok=True)
    screenshots_dir = outdir / "screenshots"
    report_path = outdir / "transcript.json"

    track_count = activity.count_audio_tracks(video_path)
    report = {"video": str(video_path), "audio": None, "system_audio": None,
              "speech_segments": [], "screenshots": [], "transcript_segments": [], "correlations": []}

    for track, source in enumerate(SOURCES[:track_count]):
        name = source["source"]
        audio_path = outdir / source["wav"]
        report["audio" if name == "mic" else "system_audio"] = str(audio_path)

        print(f"[{name}] Extracting audio track...")
        activity.extract_audio(video_path, audio_path, track=track)

        print(f"[{name}] Detecting speech activity...")
        segments = activity.detect_speech_segments(
            audio_path,
            noise_threshold_db=noise_threshold_db,
            min_silence_duration=min_silence_duration,
        )
        print(f"[{name}] Found {len(segments)} speech segment(s).")

        print(f"[{name}] Extracting screenshots...")
        shots = screenshots.extract_frames_for_segments(
            video_path, segments, screenshots_dir, lead_in=lead_in, prefix=source["screenshot_prefix"])

        print(f"[{name}] Transcribing audio via Mistral...")
        response = transcribe.transcribe_audio(audio_path)
        transcript_segments = transcribe.extract_segments(response)

        print(f"[{name}] Correlating transcript with screenshots...")
        correlations = correlate.correlate(transcript_segments, shots)

        for key, items in [("speech_segments", [asdict(s) for s in segments]),
                           ("screenshots", shots),
                           ("transcript_segments", transcript_segments),
                           ("correlations", correlations)]:
            report[key].extend({**item, "source": name} for item in items)

    # Interleave the sources into one timeline.
    for key in ("speech_segments", "transcript_segments", "correlations"):
        report[key].sort(key=lambda item: item["start"])
    report["screenshots"].sort(key=lambda item: item["timestamp"])

    report_path.write_text(json.dumps(report, indent=2))
    print(f"Wrote report to {report_path}")


def build_parser():
    parser = argparse.ArgumentParser(prog="audio-screenshotter")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="List avfoundation capture devices").set_defaults(func=cmd_devices)

    p_record = sub.add_parser("record", help="Record screen + mic + system audio (press 'q' to stop, 'p' to pause)")
    p_record.add_argument("-o", "--output", default=None,
                           help="Video output path (defaults to recordings/recording_<timestamp>.mov)")
    p_record.add_argument("--video-device", default=None,
                           help="avfoundation video device index (defaults to the cached value, then '1')")
    p_record.add_argument("--audio-device", default=None,
                           help="avfoundation audio device index (defaults to the cached value, then '0')")
    p_record.add_argument("--framerate", type=int, default=15)
    p_record.add_argument("--no-system-audio", action="store_true",
                           help="Don't record system audio (e.g. VoiceOver) as a second audio track")
    p_record.set_defaults(func=cmd_record)

    p_analyze = sub.add_parser("analyze", help="Analyze an existing recording")
    p_analyze.add_argument("video", help="Path to a recorded video file")
    p_analyze.add_argument("-o", "--outdir", default=None,
                            help="Output directory (defaults to output/<video-name>/)")
    p_analyze.add_argument("--noise-threshold", type=float, default=-30.0,
                            help="dB threshold below which audio is considered silence")
    p_analyze.add_argument("--min-silence", type=float, default=0.6,
                            help="Minimum silence duration (s) to split speech segments")
    p_analyze.add_argument("--lead-in", type=float, default=0.3,
                            help="Seconds after a segment starts to take the screenshot")
    p_analyze.set_defaults(func=cmd_analyze)

    p_run = sub.add_parser("run", help="Record, then analyze, in one go")
    p_run.add_argument("-o", "--output", default=None,
                        help="Video output path (defaults to recordings/recording_<timestamp>.mov)")
    p_run.add_argument("--outdir", default=None,
                        help="Output directory (defaults to output/<video-name>/)")
    p_run.add_argument("--video-device", default=None,
                        help="avfoundation video device index (defaults to the cached value, then '1')")
    p_run.add_argument("--audio-device", default=None,
                        help="avfoundation audio device index (defaults to the cached value, then '0')")
    p_run.add_argument("--framerate", type=int, default=15)
    p_run.add_argument("--no-system-audio", action="store_true",
                        help="Don't record system audio (e.g. VoiceOver) as a second audio track")
    p_run.add_argument("--noise-threshold", type=float, default=-30.0)
    p_run.add_argument("--min-silence", type=float, default=0.6)
    p_run.add_argument("--lead-in", type=float, default=0.3)
    p_run.set_defaults(func=cmd_run)

    return parser


def main():
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

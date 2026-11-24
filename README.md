# audio-screenshotter

Record screen + mic narration, then extract screenshots aligned to a transcript.

Documentation: [joshuacurry.dev/audio-screenshotter](https://joshuacurry.dev/audio-screenshotter)

Record your screen and microphone at the same time (e.g. narrating a walkthrough
of a website or app), then automatically:

1. detect when you were talking (audio activity detection via ffmpeg `silencedetect`)
2. pull a screenshot from the video at each speech segment
3. transcribe the audio with Mistral's Voxtral speech-to-text API
4. correlate transcript text with the nearest screenshot and write it all to
   a single `transcript.json`

The result is a set of screenshots, each paired with what you were saying at
that moment: a quick way to turn a narrated walkthrough into documentation,
a bug report or a review. See [`transcript.json` shape](#transcriptjson-shape)
below for the output.

## Requirements

- Python 3.9+
- `ffmpeg` and `ffprobe` on `PATH` (`brew install ffmpeg`)
- A [Mistral API key](https://console.mistral.ai/api-keys) for transcription
- **macOS** for the built-in `record` and `run` commands, which capture with
  ffmpeg's `avfoundation` input. `analyze` works on any OS; see
  [Recording on Linux or Windows](#recording-on-linux-or-windows).

## Install

```bash
git clone https://github.com/lucidbeaming/audio-screenshotter.git
cd audio-screenshotter
python3 -m venv audishot
source audishot/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in MISTRAL_API_KEY
```

## Configuration

| Variable          | Required | Description                                           |
| ----------------- | -------- | ----------------------------------------------------- |
| `MISTRAL_API_KEY` | Yes      | Used by `analyze`/`run` to call Voxtral speech-to-text |

`.env` is gitignored; never commit it.

## macOS permissions

The terminal app you run this from (Terminal, iTerm, etc.) needs both
**Screen Recording** and **Microphone** permission:
`System Settings > Privacy & Security > Screen Recording` /  `> Microphone`.

macOS often doesn't apply a newly-granted permission to an already-running
terminal process — if `record`/`run` fails to capture after you approve the
prompt, **fully quit and reopen the terminal app** (not just close the tab)
and try again.

## Usage

Find your screen/mic device indices (macOS asks for screen-recording and
microphone permission the first time):

```bash
python -m audio_screenshotter devices
```

This prints something like:

```
AVFoundation video devices:
[0] FaceTime HD Camera
[1] Capture screen 0
AVFoundation audio devices:
[0] MacBook Pro Microphone
```

Record. Videos and intermediate files (e.g. the extracted audio track) go in
`recordings/`, a scratch area that's gitignored but tracked as an empty
folder. While recording:

- press **p** to pause/resume (freezes capture entirely — paused time isn't
  in the final video)
- press **q** to stop; the file is finalized cleanly (don't use Ctrl-C)

```bash
python -m audio_screenshotter record --video-device 1 --audio-device 0
# -> recordings/recording_<timestamp>.mov
```

The device indices you pass are cached in `.audio_screenshotter_devices.json`
(gitignored, machine-specific), so on future runs you can omit
`--video-device`/`--audio-device` entirely and the last-used values are
reused automatically. Pass either flag again to override the cache.

Analyze an existing recording (extracts screenshots, transcribes, correlates).
Each run creates a new timestamped folder under `output/`, also gitignored
but tracked as an empty folder:

```bash
python -m audio_screenshotter analyze recordings/recording_20260929_153000.mov
# -> output/<timestamp>_recording_20260929_153000/
```

Or do both in one step:

```bash
python -m audio_screenshotter run --video-device 1 --audio-device 0
```

Each analysis run's output folder contains:

```
output/20260929_153512_recording_20260929_153000/
  audio.wav
  screenshots/
    screenshot_0000.png
    screenshot_0001.png
    ...
  transcript.json
```

### `transcript.json` shape

```json
{
  "video": "recordings/demo.mov",
  "audio": "recordings/demo_analysis/audio.wav",
  "speech_segments": [{"start": 1.2, "end": 4.8}],
  "screenshots": [{"file": "...", "timestamp": 1.5, "segment_start": 1.2, "segment_end": 4.8}],
  "transcript_segments": [{"start": 1.2, "end": 4.8, "text": "So here on the dashboard..."}],
  "correlations": [
    {
      "start": 1.2, "end": 4.8,
      "text": "So here on the dashboard...",
      "screenshot": "recordings/demo_analysis/screenshots/screenshot_0000.png",
      "screenshot_timestamp": 1.5
    }
  ]
}
```

## Tuning activity detection

- `--noise-threshold` (default `-30.0` dB): lower it (e.g. `-40`) if quiet
  speech is being missed; raise it if background hum is triggering false
  segments.
- `--min-silence` (default `0.6`s): minimum gap treated as a pause between
  segments.
- `--lead-in` (default `0.3`s): how far into a speech segment to take the
  screenshot, so the on-screen action has caught up with the narration.

## Recording on Linux or Windows

`record` and `run` use macOS-only capture (ffmpeg's `avfoundation` input and
the Unix terminal key handling for pause). On other systems, record with
ffmpeg directly and press **q** in the ffmpeg window to stop, then run
`analyze` on the file. Any video with an audio track that ffmpeg can read
works.

Linux (X11 screen + PulseAudio/PipeWire default microphone):

```bash
ffmpeg -f x11grab -framerate 15 -i "$DISPLAY" -f pulse -i default \
  -c:v libx264 -preset ultrafast -c:a aac recordings/walkthrough.mkv
python -m audio_screenshotter analyze recordings/walkthrough.mkv
```

On Wayland, `x11grab` only sees XWayland windows; record with a portal-based
tool such as OBS or GNOME's built-in recorder (with a microphone source
enabled) instead, then `analyze` the result.

Windows (list microphone names first with
`ffmpeg -list_devices true -f dshow -i dummy`):

```powershell
ffmpeg -f gdigrab -framerate 15 -i desktop -f dshow -i audio="Microphone (Realtek Audio)" `
  -c:v libx264 -preset ultrafast -c:a aac recordings\walkthrough.mkv
python -m audio_screenshotter analyze recordings\walkthrough.mkv
```

## How it works

1. `activity.py` runs ffmpeg's `silencedetect` filter over the audio track and
   turns the silence boundaries into speech segments.
2. `screenshots.py` grabs one frame per segment, `--lead-in` seconds after it
   starts.
3. `transcribe.py` sends the extracted `audio.wav` to Mistral's
   `voxtral-mini-latest` model and keeps the timestamped segments.
4. `correlate.py` pairs each transcript segment with a screenshot taken
   inside it, or failing that the nearest one in time, and writes
   `transcript.json`.

## Development

- `main` is the stable branch; active work happens on `dev`.
- Virtualenv is named `audishot/` (not `.venv`) — activate with
  `source audishot/bin/activate`. It's gitignored; recreate it with
  `python3 -m venv audishot && pip install -r requirements.txt` on a new
  machine or if it's missing.
- `.env` with `MISTRAL_API_KEY` must exist locally (gitignored, not in the
  repo) — copy from `.env.example` and fill it in again if it's ever lost.
- Device indices are cached per-machine in
  `.audio_screenshotter_devices.json` (gitignored). If missing/stale, rerun
  `python -m audio_screenshotter devices` to find them again.

## Related projects

- [mutant](https://github.com/lucidbeaming/mutant): desktop batch media
  converter built on ffmpeg and ImageMagick
- [ffmpeg-utilities](https://github.com/lucidbeaming/ffmpeg-utilities): a
  collection of ffmpeg scripts and snippets

## License

[MIT](LICENSE).

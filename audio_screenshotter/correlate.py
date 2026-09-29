"""Correlate transcript segments with the nearest screenshot in time."""


def correlate(transcript_segments: list, screenshots: list) -> list:
    """For each transcript segment, attach the screenshot whose timestamp
    falls inside the segment, or failing that, the closest one overall.
    """
    correlations = []
    for seg in transcript_segments:
        best = None
        best_key = None
        for shot in screenshots:
            ts = shot["timestamp"]
            inside = seg["start"] <= ts <= seg["end"]
            distance = 0.0 if inside else min(abs(ts - seg["start"]), abs(ts - seg["end"]))
            key = (0 if inside else 1, distance)
            if best_key is None or key < best_key:
                best_key = key
                best = shot

        correlations.append({
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"],
            "screenshot": best["file"] if best else None,
            "screenshot_timestamp": best["timestamp"] if best else None,
        })
    return correlations

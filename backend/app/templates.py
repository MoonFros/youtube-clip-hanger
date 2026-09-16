"""Fair Use template registry (spec §4 + new Template 6)."""
from __future__ import annotations

from typing import Any, Dict

TEMPLATES: Dict[str, Dict[str, Any]] = {
    "cinematic_zoom": {
        "id": "cinematic_zoom",
        "name": "Cinematic Zoom",
        "emoji": "🎬",
        "tagline": "Slow zoom-in + Ken Burns + micro-cuts. Letterbox removed, reframed 9:16.",
        "desc": ("Slow 10–15% zoom-in on the focal point, subtle Ken Burns pan across "
                 "static frames, letterbox bars removed and reframed to 9:16 vertical, "
                 "dynamic word-by-word captions with drop shadow, micro-cut every ~6s "
                 "to break the visual fingerprint."),
        "elements": ["captions", "reframe", "zoom", "microcut", "audio_duck"],
        "microcut_every": 6.0,
        "default_audio": {"music": "auto"},
    },
    "split_screen": {
        "id": "split_screen",
        "name": "Split Screen Commentary Frame",
        "emoji": "📱",
        "tagline": "Top 60% clip / bottom 40% waveform + captions + motion background.",
        "desc": ("Top 60%: the original clip reframed and zoomed 10%. Bottom 40%: animated "
                 "waveform visualizer, dynamic captions and a subtle looping gradient "
                 "background. The layout change alone is a strong transformative element."),
        "elements": ["layout", "captions", "graphics", "reframe", "audio_duck"],
        "microcut_every": 6.0,
        "default_audio": {"music": "auto"},
    },
    "caption_storm": {
        "id": "caption_storm",
        "name": "Caption Storm",
        "emoji": "⚡",
        "tagline": "Aggressive 15–20% zoom, Hormozi-style pop-in captions, grain + grade.",
        "desc": ("Full-screen 9:16 with aggressive 15–20% zoom to fill the vertical frame. "
                 "Large animated word-by-word captions pop in with bounce/scale, keywords "
                 "color-highlighted, subtle film grain + warm color grade to alter the "
                 "visual fingerprint."),
        "elements": ["captions", "reframe", "zoom", "grade", "grain", "audio_duck"],
        "microcut_every": 5.5,
        "default_audio": {"music": "auto"},
    },
    "reaction_frame": {
        "id": "reaction_frame",
        "name": "Reaction Frame",
        "emoji": "🖼️",
        "tagline": "Rounded 70% window over blurred clip + 'Did you know?' card + progress bar.",
        "desc": ("Main clip in a rounded-corner window (70% of screen) over a blurred copy "
                 "of the same clip, auto-generated context text overlay at the top pulled "
                 "from the AI scene summary, progress bar at the bottom."),
        "elements": ["layout", "graphics", "captions", "reframe", "blur", "audio_duck"],
        "microcut_every": 6.5,
        "default_audio": {"music": "auto"},
    },
    "minimal_clean": {
        "id": "minimal_clean",
        "name": "Minimal Clean",
        "emoji": "🎞️",
        "tagline": "Smart 9:16 reframe, clean bottom-third captions, 1.04x speed ramp.",
        "desc": ("9:16 reframe with the subject kept centered, clean bottom-third captions, "
                 "slight 1.04x speed ramp on non-dialogue moments to break the fingerprint "
                 "without being noticeable. Dialogue preserved, music ducked."),
        "elements": ["captions", "reframe", "speed", "audio_duck"],
        "microcut_every": 7.0,
        "default_audio": {"music": "duck"},
    },
    "breakdown_bookend": {
        "id": "breakdown_bookend",
        "name": "The Breakdown Bookend",
        "emoji": "📖",
        "tagline": "AI hook intro (3s) → raw scene → AI outro question (3s).",
        "desc": ("0:00–0:03 fast-cut hook with AI voice + animated title card (original audio "
                 "ducked to 15%). 0:03–end: the raw scene, zoomed 10% with dynamic subtitles, "
                 "dialogue at 100%. Last 3s: smooth outro slide with the AI asking a "
                 "discussion question + follow handle. The highest-rated format for "
                 "engagement + transformation."),
        "elements": ["layout", "captions", "tts", "reframe", "microcut", "audio_duck"],
        "microcut_every": 6.0,
        "default_audio": {"music": "auto"},
        "bookend": True,
    },
}

DEFAULT_TEMPLATE = "cinematic_zoom"

ORDER = ["cinematic_zoom", "split_screen", "caption_storm",
         "reaction_frame", "minimal_clean", "breakdown_bookend"]


def template_list_public() -> list:
    return [TEMPLATES[k] for k in ORDER]

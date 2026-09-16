"""FairClip backend configuration."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # backend/
REPO_ROOT = ROOT.parent
ASSETS = Path(__file__).resolve().parent / "assets"
FONTS = ASSETS / "fonts"
TTS_VENDOR = ROOT / "tts" / "vendor"
TTS_BRIDGE = ROOT / "tts" / "tts.js"
DATA_DIR = Path(os.environ.get("FAIRCLIP_DATA", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---- Tiers -----------------------------------------------------------------
TIERS = {
    "free": {
        "label": "Free",
        "max_clip_seconds": 60,
        "daily_clip_limit": 5,
        "max_render_width": 720,      # 720x1280
        "watermark_forced": True,
        "export_presets": [(720, 1280)],
        "bulk_processing": False,
    },
    "pro": {
        "label": "Pro",
        "max_clip_seconds": 300,
        "daily_clip_limit": 10000,
        "max_render_width": 1080,     # 1080x1920 (4K available on-demand)
        "watermark_forced": False,
        "export_presets": [(720, 1280), (1080, 1920)],
        "bulk_processing": True,
    },
}
PRO_PRICE = "$9/mo"

# ---- Fair Use hard rules (spec §3) ----------------------------------------
RULE1_MAX_UNMODIFIED_VIDEO_S = 7.0   # no continuous unmodified video > 7s
RULE2_MAX_MUSIC_S = 5.0              # no continuous copyrighted music > 5s
RULE2_MAX_MUSIC_VOLUME = 0.25        # ... at >25% volume
MUSIC_DUCK_GAIN = 0.18               # duck to 15-20%
SILENCE_GAP_EVERY_S = 5.0            # micro-silence cadence
SILENCE_GAP_LEN_S = 0.5
MICROCUT_INTERVAL_S = 6.0            # default micro-cut cadence (5-7s)
ASPECT_SOURCE = (16, 9)
ASPECT_OUTPUT = (9, 16)
DISCLAIMER_TEXT = "This clip is transformative commentary under 17 U.S.C. \u00a7 107."
LEGAL_DISCLAIMER = (
    "FairClip applies automated transformations to help your clips qualify as "
    "transformative works under Fair Use doctrine (17 U.S.C. \u00a7 107). However, "
    "Fair Use is a legal defense determined by courts on a case-by-case basis. "
    "No automated tool can guarantee immunity from copyright claims. We recommend "
    "adding your own commentary or creative input for the strongest Fair Use "
    "protection."
)

# ---- Pipeline ---------------------------------------------------------------
PREVIEW_MAX_HEIGHT = 720
WAVEFORM_BUCKETS = 1200              # waveform samples for the UI
ENVELOPE_DT = 0.05                   # stem envelope resolution (s)
JOB_RETENTION_HOURS = 24             # auto-delete after 24h (free tier)
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024

# ---- External AI (optional, env-configured) --------------------------------
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
WHISPER_MODEL = os.environ.get("FAIRCLIP_WHISPER_MODEL", "base")

# Bookend TTS voice presets -> (mespeak voice, espeak variant, label, description)
TTS_VOICES = {
    "deep":   ("en-rp", "m3", "Deep Cinematic", "Low, gravitating, trailer-voice energy"),
    "story":  ("en-us", "m1", "Storyteller",     "Warm narrator with steady pacing"),
    "casual": ("en-us", "m5", "Casual Guy",      "Relaxed, conversational tone"),
    "energetic": ("en-us", "f2", "Energetic Girl", "Bright, punchy, fast"),
    "hype":   ("en-us", "f4", "Hype Host",       "High-energy reaction-host cadence"),
}

HOOK_STYLES = {
    "A": "Did You Know / Trivia",
    "B": "Emotional / Hype",
    "C": "Curiosity / Question",
}

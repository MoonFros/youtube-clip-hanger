"""Bookend Commentary script engine.

Generates 3 hook styles (intro) + an outro CTA for a selected scene.

Provider chain:
  1. OpenAI-compatible chat completions (GPT-4o-mini / Claude-compatible)
     when OPENAI_API_KEY is set — best quality.
  2. Local rule-based engine (offline): extracts salient phrases from the
     scene transcript and fills cinematic hook templates.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .config import HOOK_STYLES, OPENAI_API_KEY, OPENAI_BASE_URL

# ---------------- local (offline) engine ------------------------------------

_STOP = set("a an the and or but if then so of to in on at for with about into over "
            "under from by as is are was were be been being it its this that these "
            "those i you he she we they me him her us them my your his their not no "
            "yes do does did have has had will would can could just really very so".split())


def _key_phrases(words: List[Dict[str, float]], t0: float, t1: float,
                 n: int = 4) -> List[str]:
    inside = [w["w"].strip(".,!?;:'\"") for w in words
              if t0 <= w["t0"] < t1 and w["w"].strip() not in _STOP
              and len(w["w"].strip()) > 2]
    if not inside:
        return []
    # keep order of appearance, dedupe
    seen, out = set(), []
    for w in inside:
        k = w.lower()
        if k not in seen:
            seen.add(k)
            out.append(w)
        if len(out) >= n:
            break
    return out


_LOCAL_HOOKS = {
    "A": [
        "The crazy detail you missed in this scene: {p1}.",
        "Nobody talks about this part — {p1}.",
        "Here's the detail 99% of viewers missed: {p1}.",
    ],
    "B": [
        "This is still one of the most intense moments ever captured.",
        "Chills. Every single time. This scene does not age.",
        "Watch this closely — this is why everyone is still talking about it.",
    ],
    "C": [
        "Wait until you see how they handled {p1}.",
        "What happens next changes everything — and it starts here.",
        "Can you spot the twist before it hits? Watch to the end.",
    ],
}
_LOCAL_OUTROS = [
    "Did you catch that? Tell me in the comments.",
    "What would you have done? Drop your take below.",
    "If this scene hit different, follow for more breakdowns.",
]


def _local_generate(transcript_words: List[Dict[str, float]], t0: float, t1: float,
                    style: str) -> Dict[str, str]:
    style = style if style in HOOK_STYLES else "B"
    phrases = _key_phrases(transcript_words, t0, t1, 3)
    p1 = phrases[0].lower() if phrases else "this moment"
    p2 = phrases[1].lower() if len(phrases) > 1 else p1
    hook = _LOCAL_HOOKS[style][hash((p1, style)) % len(_LOCAL_HOOKS[style])]
    hook = hook.format(p1=p1, p2=p2)
    fact = " / ".join(phrases[:3]).title() if phrases else "the tension in this scene"
    outro = _LOCAL_OUTROS[hash(p1) % len(_LOCAL_OUTROS)]
    return {"style": style, "style_label": HOOK_STYLES[style],
            "intro": hook[:160], "outro": outro[:120], "fact": fact[:90]}


# ---------------- OpenAI-compatible provider --------------------------------

def generate_bookend_script(
    words: List[Dict[str, float]],
    sentences: List[Dict[str, Any]],
    t0: float,
    t1: float,
    style: str = "auto",
) -> Dict[str, Any]:
    """style: A|B|C|auto (auto picks the strongest match)."""
    if OPENAI_API_KEY:
        try:
            r = _openai_generate(words, sentences, t0, t1, style)
            if r:
                return r
        except Exception:
            pass
    local = _local_generate(words, t0, t1, style)
    local["engine"] = "fairclip-local-script-engine"
    # auto: surface all three styles so the UI can offer the choice
    all_styles = {}
    for s in ("A", "B", "C"):
        all_styles[s] = _local_generate(words, t0, t1, s)["intro"]
    local["styles"] = all_styles
    return local


def _openai_generate(words, sentences, t0, t1, style):
    import httpx
    scene_text = " ".join(s["s"] for s in sentences if s["t0"] >= t0 - 1 and s["t1"] <= t1 + 1)
    if len(scene_text) < 20:
        scene_text = " ".join(w["w"] for w in words if t0 <= w["t0"] < t1)
    if not scene_text.strip():
        return None
    scene_text = scene_text[:900]
    prompt = (
        "You are a short-form video hook writer. The scene transcript is: \"\"\"\n"
        f"{scene_text}\n\"\"\"\n"
        "Write:\n"
        f"1) An INTRO hook of at most 14 words for style {style or 'A'} "
        "(A = did-you-know trivia, B = emotional hype, C = curiosity question).\n"
        "2) A ONE-SENTENCE fact/context line (max 15 words) that could appear as a top "
        "overlay ('Did you know? ...').\n"
        "3) An OUTRO of at most 12 words ending with a question that drives comments.\n"
        "Reply as JSON: {\"intro\": ..., \"fact\": ..., \"outro\": ...}"
    )
    r = httpx.post(
        f"{OPENAI_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        json={"model": "gpt-4o-mini",
              "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.8, "max_tokens": 220},
        timeout=90,
    )
    if r.status_code != 200:
        return None
    content = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return None
    data = json.loads(m.group(0))
    out = {
        "style": style if style in HOOK_STYLES else "A",
        "style_label": HOOK_STYLES.get(style, HOOK_STYLES["A"]),
        "intro": str(data.get("intro", ""))[:160],
        "fact": str(data.get("fact", ""))[:90],
        "outro": str(data.get("outro", ""))[:120],
        "engine": "gpt-4o-mini",
    }
    if out["intro"]:
        return out
    return None

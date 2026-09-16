"""Render all 6 templates on the synthetic test clip; verify outputs."""
import sys, time, os
sys.path.insert(0, ".")
import shutil

import numpy as np

from app.config import DATA_DIR
from app.engine import probe, decode_audio
from app import analysis
from app.stems import separate_stems, SR
from app.store import STORE
from app.render import build_plan, run_render
from app.preflight import frame_similarity_timeline, check_render
from app.templates import ORDER

SRC = "/tmp/testvideo.mp4"
job = STORE.create_job("upload", source="testvideo.mp4", name="Tpl test")
job.source_path = SRC
d = DATA_DIR / job.id
d.mkdir(parents=True, exist_ok=True)
job.preview_path = str(d / "preview.mp4")
shutil.copyfile(SRC, job.preview_path)
info = probe(SRC)
job.duration, job.width, job.height, job.fps = info["duration"], info["width"], info["height"], info["fps"]
job.has_audio = True
job.letterbox = analysis.detect_letterbox(SRC)
print("letterbox:", job.letterbox)
x, sr = decode_audio(SRC, sr=SR, mono=True)
res = separate_stems(x[0])
np.savez_compressed(d / "stems.npz", dialogue=res["dialogue"], music=res["music"], sfx=res["sfx"])
job.stems = {"status": "ready", "env": res["env"]}
# fake transcript so captions exercise
words = []
import itertools
text = "This is a test scene with some dramatic words and punctuation! Did you see that?"
i = 0
for w in text.split():
    words.append({"w": w, "t0": 1.0 + i * 0.35, "t1": 1.35 + i * 0.35})
    i += 1
job.transcript = {"status": "ready", "engine": "fake", "text": text, "words": words,
                  "sentence_spans": []}

clip = STORE.create_clip(job.id, 1.0, 10.0, "All templates")
opts = {"width": 720, "height": 1280, "fps": 30, "format": "mp4",
        "watermark": True, "disclaimer": True, "crf": 22}

for tpl in ORDER:
    clip.bookend = {"enabled": True, "style": "B", "voice": "story",
                    "intro_text": "This is the most intense moment in the whole series.",
                    "outro_text": "What would you have done? Tell me below.",
                    "fact": "The reactor scene was shot in a single take.",
                    "tts_status": "pending"}
    t0 = time.time()
    try:
        plan = build_plan(job, clip, tpl, dict(opts), STORE)
        out = str(d / f"render_{tpl}.mp4")
        run_render(plan, out)
        p = probe(out)
        print(f"OK  {tpl:20s} {time.time()-t0:5.1f}s  {p['width']}x{p['height']} "
              f"{p['duration']:.1f}s {os.path.getsize(out)//1024}KB "
              f"bookend={plan.get('bookend_on')}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"FAIL {tpl}: {e}")
print("DONE")

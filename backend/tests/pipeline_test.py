"""End-to-end pipeline test on the synthetic 12s test video."""
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

SRC = "/tmp/testvideo.mp4"

job = STORE.create_job("upload", source="testvideo.mp4", name="Pipeline test")
job.source_path = SRC
d = DATA_DIR / job.id
d.mkdir(parents=True, exist_ok=True)
job.preview_path = str(d / "preview.mp4")
shutil.copyfile(SRC, job.preview_path)

t0 = time.time()
info = probe(SRC)
job.duration, job.width, job.height, job.fps = info["duration"], info["width"], info["height"], info["fps"]
job.has_audio = info["has_audio"]
print("probe: %.2fs" % (time.time() - t0))

t0 = time.time()
job.letterbox = analysis.detect_letterbox(SRC)
print("letterbox:", job.letterbox, "%.2fs" % (time.time() - t0))

t0 = time.time()
job.scenes = analysis.detect_scenes(SRC)
print("scenes:", job.scenes, "%.2fs" % (time.time() - t0))

t0 = time.time()
job.waveform = analysis.audio_envelope(SRC)
print("waveform buckets:", len(job.waveform["rms"]), "%.2fs" % (time.time() - t0))

t0 = time.time()
x, sr = decode_audio(SRC, sr=SR, mono=True)
res = separate_stems(x[0])
np.savez_compressed(d / "stems.npz", dialogue=res["dialogue"], music=res["music"], sfx=res["sfx"])
job.stems = {"status": "ready", "env": res["env"]}
print("stems: %.2fs, env bins=%d" % (time.time() - t0, len(res["env"]["rms"])))
print("  peak dlg/music/sfx:",
      round(float(np.max(np.abs(res['dialogue']))), 3),
      round(float(np.max(np.abs(res['music']))), 3),
      round(float(np.max(np.abs(res['sfx']))), 3))

job.transcript = {"status": "unavailable", "words": []}

clip = STORE.create_clip(job.id, 1.0, 10.0, "Test clip")

t0 = time.time()
plan = build_plan(job, clip, "cinematic_zoom",
                  {"width": 720, "height": 1280, "fps": 30, "format": "mp4",
                   "watermark": True, "disclaimer": True, "crf": 22}, STORE)
print("plan built: %.2fs D=%.1f words=%d stems=%s" % (
    time.time() - t0, plan["D"], len(plan["words"]), plan["stems"] is not None))

t0 = time.time()
out = str(d / "render_test.mp4")
progress = []
run_render(plan, out, lambda p, s: progress.append((p, s)))
print("render: %.1fs frames=%d size=%dKB last_progress=%s" % (
    time.time() - t0, int(plan["D"] * 30), os.path.getsize(out) // 1024, progress[-1] if progress else None))
print("probe out:", probe(out))

t0 = time.time()
sims = frame_similarity_timeline(out, SRC, plan["t0"], plan["t1"])
print("sim timeline: %.2fs avg=%.3f" % (time.time() - t0, float(np.mean(sims))))

r = STORE.create_render(clip, "cinematic_zoom", plan and {"width": 720})
r.output_path = out
r.duration = probe(out)["duration"]
r.audio_plan = plan.get("audio_plan", {})
pf = check_render(r, sims)
print("preflight score:", pf["score"], pf["verdict"])
print("rules:", {k: (v.get("pass") if "pass" in v else v.get("elements")) for k, v in pf["rules"].items()})
print("warnings:", [w["msg"] for w in pf["warnings"]])
print("OK")

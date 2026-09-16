import sys
sys.path.insert(0, ".")
import numpy as np
from app import render as R
from app.store import STORE, Job
from app.config import DATA_DIR

job = Job(id="jx", source_type="upload", source_path="/tmp/testvideo.mp4",
          preview_path="/tmp/testvideo.mp4")
job.duration, job.width, job.height, job.fps = 12.0, 640, 360, 30
job.letterbox = {"top": 20, "bottom": 20}
job.transcript = {"words": [{"w": "hello", "t0": 1.0, "t1": 1.3}]}
job.stems = {"env": {"rms": [0.5] * 200, "music": [0.4] * 200,
                     "dialogue": [0.5] * 200, "sfx": [0.1] * 200}}
import numpy as np
d = DATA_DIR / "jx"
d.mkdir(parents=True, exist_ok=True)
np.savez_compressed(d / "stems.npz", dialogue=np.zeros(12 * 48000, np.float32),
                    music=np.zeros(12 * 48000, np.float32),
                    sfx=np.zeros(12 * 48000, np.float32))
clip = STORE.create_clip(job.id, 1.0, 8.0, "repro")
plan = R.build_plan(job, clip, "reaction_frame",
                    {"width": 720, "height": 1280, "fps": 30, "watermark": True},
                    STORE)
print("pop_frames type:", type(plan["pop_frames"]), list(plan["pop_frames"])[:4])
img = np.zeros((360, 640, 3), dtype=np.uint8)
out = R.frames_reaction_frame(plan, img, 2.0, 0, 720, 1280)
print("frame ok:", out.shape, out.dtype)

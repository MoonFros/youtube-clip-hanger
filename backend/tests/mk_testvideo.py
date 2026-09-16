import sys, time
sys.path.insert(0, ".")
import numpy as np
from app.engine import mux_output, probe

W, H, FPS = 640, 360, 30
n = 12 * FPS
BAR = 20

def gen():
    CH_ = H - 2 * BAR
    for i in range(n):
        t = i / FPS
        yy, xx = np.mgrid[0:CH_, 0:W]
        frame = np.zeros((H, W, 3), dtype=np.uint8)
        ones = np.ones((CH_, W))
        content = np.stack([
            120 + 60 * np.sin(t * 0.8 + xx * 0.01),
            80 + 40 * np.cos(t * 0.5 + yy * 0.02),
            150 + 50 * np.sin(t * 1.1) * ones,
        ], axis=2).astype(np.uint8)
        content = np.roll(content, int(t * 20), axis=1)
        frame[BAR:H - BAR] = content
        yield frame

audio = np.sin(2 * np.pi * 440 * np.arange(12 * 48000) / 48000).astype(np.float32) * 0.3
audio = np.stack([audio, audio], axis=0)
t0 = time.time()
mux_output("/tmp/testvideo.mp4", W, H, FPS, gen(), audio=audio, audio_sr=48000,
           crf=23, preset="ultrafast")
print("test video: %.1fs" % (time.time() - t0), probe("/tmp/testvideo.mp4"))

"use client";

import { useEffect, useRef, useState } from "react";
import { ClipPublic, JobPublic, Word, fmtTime } from "../lib/api";

const TPL: Record<string, { zoom: [number, number]; capStyle: string }> = {
  cinematic_zoom: { zoom: [1.1, 1.16], capStyle: "clean" },
  split_screen: { zoom: [1.1, 1.1], capStyle: "clean" },
  caption_storm: { zoom: [1.18, 1.18], capStyle: "storm" },
  reaction_frame: { zoom: [1.08, 1.12], capStyle: "small" },
  minimal_clean: { zoom: [1.05, 1.05], capStyle: "clean" },
  breakdown_bookend: { zoom: [1.1, 1.1], capStyle: "clean" },
};

export default function PhonePreview({
  jobId,
  job,
  clip,
  words,
  playhead,
}: {
  jobId: string;
  job: JobPublic;
  clip: ClipPublic;
  words: Word[];
  playhead: (t: number) => void;
}) {
  const vidRef = useRef<HTMLVideoElement>(null);
  const vid2Ref = useRef<HTMLVideoElement>(null);
  const [t, setT] = useState(clip.start);
  const [playing, setPlaying] = useState(false);
  const [zoomed, setZoomed] = useState(true);

  const tpl = TPL[clip.template] || TPL.cinematic_zoom;
  const localDur = Math.max(0.5, clip.end - clip.start);
  const localT = Math.min(localDur, Math.max(0, t - clip.start));
  const p = localT / localDur;

  // keep video time inside the clip window (loop)
  useEffect(() => {
    const v = vidRef.current;
    if (!v) return;
    const onTime = () => {
      let ct = v.currentTime;
      if (ct < clip.start - 0.05 || ct >= clip.end) ct = clip.start;
      v.currentTime = ct;
      setT(ct);
      playhead(ct);
      if (vid2Ref.current) vid2Ref.current.currentTime = ct;
    };
    v.addEventListener("timeupdate", onTime);
    return () => v.removeEventListener("timeupdate", onTime);
  }, [clip.start, clip.end, playhead]);

  // seek when clip changes
  useEffect(() => {
    const v = vidRef.current;
    if (v) {
      v.currentTime = clip.start;
      v.play().catch(() => {});
      setPlaying(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clip.id]);

  const currentWords = words.filter((w) => w.t1 >= localT && w.t0 <= localT + 0.75).map((w) => w.w);
  const wordText = currentWords.join(" ");

  const zoom = zoomed ? 1 + (tpl.zoom[1] - tpl.zoom[0]) * p : 1.0;
  const isBookendIntro = clip.template === "breakdown_bookend" && clip.bookend.enabled && localT < Math.min(3, localDur * 0.3);
  const isBookendOutro = clip.template === "breakdown_bookend" && clip.bookend.enabled && localT > localDur - Math.min(3, localDur * 0.3);

  const toggle = () => {
    const v = vidRef.current;
    if (!v) return;
    if (v.paused) {
      v.play().catch(() => {});
      setPlaying(true);
    } else {
      v.pause();
      setPlaying(false);
    }
  };

  const seek = (lt: number) => {
    const v = vidRef.current;
    if (!v) return;
    const nt = clip.start + lt;
    v.currentTime = nt;
    if (vid2Ref.current) vid2Ref.current.currentTime = nt;
    setT(nt);
    playhead(nt);
  };

  return (
    <div className="flex min-h-0 flex-1 items-center justify-center">
      <div className="phone-frame relative h-full max-h-[560px] w-auto overflow-hidden rounded-[28px]" style={{ aspectRatio: "9/16" }}>
        {/* scene */}
        <div className="absolute inset-0 overflow-hidden bg-black">
          <div
            className="absolute inset-0"
            style={{
              transform: `scale(${zoom * (zoomed ? 1 : 1)})`,
              transformOrigin: "center 45%",
              transition: "transform 0.4s linear",
            }}
          >
            <video
              ref={vidRef}
              src={`/media/jobs/${jobId}/preview`}
              muted
              playsInline
              className={`h-full w-full ${clip.template === "reaction_frame" ? "scale-110 blur-2xl brightness-50" : "object-cover"}`}
            />
          </div>

          {/* template overlays */}
          {clip.template === "cinematic_zoom" && (
            <div className="pointer-events-none absolute inset-0" style={{ boxShadow: "inset 0 0 120px rgba(0,0,0,0.55)" }} />
          )}
          {clip.template === "caption_storm" && (
            <div
              className="pointer-events-none absolute inset-0 opacity-40 mix-blend-overlay"
              style={{
                backgroundImage:
                  "repeating-linear-gradient(0deg, rgba(255,255,255,0.06) 0 1px, transparent 1px 3px)",
              }}
            />
          )}
          {clip.template === "split_screen" && (
            <div className="absolute inset-x-0 bottom-0 h-[42%] bg-gradient-to-b from-ink-800 to-ink-950">
              <div className="flex h-full items-center justify-center gap-1 px-4">
                {Array.from({ length: 24 }).map((_, i) => (
                  <div
                    key={i}
                    className="w-1.5 rounded-full bg-accent-soft"
                    style={{
                      height: `${20 + 60 * Math.abs(Math.sin(i * 0.9 + t * 6))}%`,
                      opacity: 0.9,
                    }}
                  />
                ))}
              </div>
            </div>
          )}
          {clip.template === "reaction_frame" && (
            <>
              <video
                ref={vid2Ref}
                src={`/media/jobs/${jobId}/preview`}
                muted
                playsInline
                className="absolute left-1/2 top-[16%] h-auto w-[72%] -translate-x-1/2 rounded-2xl border border-white/30 shadow-2xl"
                style={{ objectFit: "cover", aspectRatio: "16/9" }}
              />
              <div className="absolute left-1/2 top-[4%] -translate-x-1/2 rounded-full bg-ink-950/80 px-4 py-1.5 text-[11px] font-semibold text-cyan-300 backdrop-blur">
                {clip.bookend.fact || "Did you know?"}
              </div>
              <div className="absolute inset-x-4 bottom-3 h-1 overflow-hidden rounded-full bg-white/20">
                <div className="h-full bg-cyan-400" style={{ width: `${p * 100}%` }} />
              </div>
            </>
          )}
          {clip.template === "minimal_clean" && <div className="pointer-events-none absolute inset-0" />}

          {/* bookend cards */}
          {isBookendIntro && (
            <div className="absolute inset-x-3 bottom-16 rounded-2xl bg-ink-950/85 p-4 backdrop-blur">
              <p className="text-[10px] font-bold uppercase tracking-widest text-accent-soft">Hook</p>
              <p className="mt-1 text-sm font-semibold leading-snug text-white">
                {clip.bookend.intro_text || "Generating hook…"}
              </p>
            </div>
          )}
          {isBookendOutro && (
            <div className="absolute inset-x-3 bottom-16 rounded-2xl bg-gradient-to-br from-accent/90 to-cy/70 p-4">
              <p className="text-sm font-bold leading-snug text-white">{clip.bookend.outro_text || "Follow for more"}</p>
              <p className="mt-1 text-[11px] text-white/80">@fairclip.demo</p>
            </div>
          )}

          {/* captions */}
          {wordText && !isBookendIntro && (
            <div
              className={`absolute inset-x-2 flex flex-wrap items-end justify-center gap-x-1.5 px-2 text-center ${
                clip.template === "split_screen" ? "bottom-[44%]" : "bottom-8"
              }`}
            >
              {currentWords.map((w, i) => {
                const hot = /[A-Z0-9?!.]/.test(w) && w.length > 3;
                return (
                  <span
                    key={i}
                    className={`font-extrabold uppercase leading-tight drop-shadow-[0_2px_6px_rgba(0,0,0,0.9)] ${
                      clip.template === "caption_storm"
                        ? "text-xl md:text-2xl"
                        : "text-lg"
                    } ${hot ? "text-cyan-300" : "text-white"}`}
                    style={
                      clip.template === "caption_storm"
                        ? { transform: `scale(${1 + 0.15 * Math.sin(localT * 9 + i)})` }
                        : undefined
                    }
                  >
                    {w}
                  </span>
                );
              })}
            </div>
          )}

          {/* watermark */}
          <div className="absolute bottom-1.5 right-2.5 rounded bg-black/50 px-1.5 py-0.5 text-[9px] font-semibold text-white/70">
            FairClip
          </div>
        </div>

        {/* controls */}
        <div className="absolute inset-x-0 top-0 flex items-center justify-between p-2.5">
          <button
            onClick={toggle}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-black/60 text-sm text-white backdrop-blur"
          >
            {playing ? "⏸" : "▶"}
          </button>
          <button
            onClick={() => setZoomed((z) => !z)}
            title="Toggle zoom approximation"
            className="flex h-8 items-center rounded-full bg-black/60 px-2.5 text-[11px] text-white/80 backdrop-blur"
          >
            {zoom.toFixed(2)}×
          </button>
        </div>

        {/* seek bar over clip */}
        <input
          type="range"
          min={0}
          max={localDur}
          step={0.05}
          value={localT}
          onChange={(e) => seek(parseFloat(e.target.value))}
          className="absolute bottom-0 left-0 w-full opacity-90"
        />
        <div className="absolute bottom-6 left-2.5 text-[10px] font-medium text-white/70 drop-shadow">
          {fmtTime(localT)} / {fmtTime(localDur)}
        </div>
      </div>
    </div>
  );
}

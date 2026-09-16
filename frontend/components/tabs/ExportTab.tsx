"use client";

import { useEffect, useState } from "react";
import { useApp } from "../AppProvider";
import { ClipPublic, RenderPublic, fmtTime, url } from "../../lib/api";

export default function ExportTab({
  jobId,
  clip,
  renders,
  running,
  onRendered,
}: {
  jobId: string;
  clip: ClipPublic;
  renders: RenderPublic[];
  running: boolean;
  onRendered: () => void;
}) {
  const { toast, health } = useApp();
  const plan = (health?.plan as "free" | "pro") || "free";
  const [width, setWidth] = useState(720);
  const [fps, setFps] = useState(30);
  const [format, setFormat] = useState<"mp4" | "mov">("mp4");
  const [watermark, setWatermark] = useState(true);
  const [ack, setAck] = useState(
    typeof window !== "undefined" && !!localStorage.getItem("fairclip-disclaimer")
  );
  const [showLegal, setShowLegal] = useState(false);

  const done = renders
    .filter((r) => r.status === "done")
    .sort((a, b) => b.created - a.created);
  const latest = done[0];
  const forcedWm = plan === "free";

  useEffect(() => {
    if (renders.length && !running) onRendered();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [renders.length]);

  const doRender = async () => {
    if (!ack) {
      toast("Please accept the legal disclaimer before exporting", "error");
      setShowLegal(true);
      return;
    }
    try {
      await fetch(url(`/api/clips/${clip.id}/renders`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          template: clip.template,
          options: { width, fps, format, watermark },
        }),
      }).then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail || "Render failed");
      });
      toast("Rendering started — pre-flight runs automatically after", "success");
      onRendered();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-ink-600 bg-ink-850 p-4">
        <p className="mb-3 text-sm font-semibold text-white">Export settings</p>
        <div className="grid grid-cols-2 gap-3">
          <label className="text-[11px] text-zinc-400">
            Resolution
            <select
              value={width}
              onChange={(e) => setWidth(parseInt(e.target.value))}
              className="mt-1 w-full rounded-lg border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-white outline-none"
            >
              <option value={720}>720p (1280×720 → 720×1280)</option>
              <option value={1080} disabled={plan === "free"}>
                1080p {plan === "free" ? "· PRO" : ""}
              </option>
            </select>
          </label>
          <label className="text-[11px] text-zinc-400">
            Frame rate
            <select
              value={fps}
              onChange={(e) => setFps(parseInt(e.target.value))}
              className="mt-1 w-full rounded-lg border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-white outline-none"
            >
              <option value={30}>30 fps</option>
              <option value={60}>60 fps</option>
            </select>
          </label>
          <label className="text-[11px] text-zinc-400">
            Format
            <select
              value={format}
              onChange={(e) => setFormat(e.target.value as any)}
              className="mt-1 w-full rounded-lg border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-white outline-none"
            >
              <option value="mp4">MP4 (H.264)</option>
              <option value="mov">MOV (H.264)</option>
            </select>
          </label>
          <label className="flex items-end justify-between rounded-lg border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs text-white">
            <span className="text-[11px] text-zinc-400">
              Watermark {forcedWm && <span className="text-amber-400">(Free)</span>}
            </span>
            <input
              type="checkbox"
              checked={watermark || forcedWm}
              disabled={forcedWm}
              onChange={(e) => setWatermark(e.target.checked)}
            />
          </label>
        </div>

        <label className="mt-3 flex cursor-pointer items-center gap-2 text-[11px] text-zinc-300">
          <input
            type="checkbox"
            checked={ack}
            onChange={(e) => {
              setAck(e.target.checked);
              if (e.target.checked) localStorage.setItem("fairclip-disclaimer", "1");
            }}
          />
          I understand FairClip is not legal advice and I accept the disclaimer
        </label>
        <button onClick={() => setShowLegal((s) => !s)} className="mt-1 text-[11px] text-accent-soft underline">
          {showLegal ? "hide" : "read"} the legal disclaimer
        </button>
        {showLegal && (
          <p className="mt-2 whitespace-pre-line rounded-lg bg-ink-950 p-3 text-[10px] leading-relaxed text-zinc-400">
            {health?.legal_disclaimer}
          </p>
        )}

        <button
          onClick={doRender}
          disabled={running}
          className="mt-4 w-full rounded-xl bg-gradient-to-r from-accent to-cy px-4 py-3 text-sm font-bold text-white shadow-glow transition hover:brightness-110 disabled:opacity-50"
        >
          {running ? "Rendering…" : `🚀 Render ${fmtTime(clip.duration)} clip`}
        </button>
        {plan === "free" && (
          <p className="mt-2 text-center text-[10px] text-zinc-500">
            Free plan: up to 5 clips/day, 720p, FairClip watermark ·{" "}
            <span className="text-accent-soft">Pro $9/mo: 1080p, no watermark</span>
          </p>
        )}
      </div>

      {running && (
        <div className="rounded-xl border border-ink-600 bg-ink-850 p-4">
          <p className="pulse-soft text-sm font-semibold text-white">Rendering in progress…</p>
          <p className="mt-1 text-[11px] text-zinc-500">
            Composite → encode → content-id pre-flight. Usually 30–90s for a 60s clip.
          </p>
        </div>
      )}

      {latest && (
        <div className="rounded-xl border border-emerald-800/40 bg-emerald-950/10 p-4">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-white">Latest render</p>
            <span
              className={`rounded-full px-2.5 py-0.5 text-[10px] font-bold ${
                (latest.preflight?.score ?? 0) >= 75
                  ? "bg-emerald-500/20 text-emerald-300"
                  : (latest.preflight?.score ?? 0) >= 50
                    ? "bg-amber-500/20 text-amber-300"
                    : "bg-red-500/20 text-red-300"
              }`}
            >
              Fair Use {latest.preflight?.score ?? "–"}/100
            </span>
          </div>
          <p className="mt-0.5 text-[11px] text-zinc-500">
            {(latest.preflight?.verdict || "").trim()}
          </p>
          <div className="mt-3 overflow-hidden rounded-xl border border-ink-700 bg-black" style={{ aspectRatio: "9/16", maxHeight: 320, margin: "0 auto", width: "min(100%, 220px)" }}>
            <video
              src={url(`/media/clips/${clip.id}/renders/${latest.id}/out?nocache=${latest.created}`)}
              controls
              playsInline
              className="h-full w-full object-contain"
            />
          </div>
          <a
            href={url(`/media/clips/${clip.id}/renders/${latest.id}/out?download=1`)}
            download={`fairclip_${clip.name || "clip"}.${format}`}
            className="mt-3 block w-full rounded-xl bg-accent px-4 py-2.5 text-center text-sm font-bold text-white transition hover:bg-accent-soft"
          >
            ⬇ Download {format.toUpperCase()} · {Math.round((latest.size || 0) / 1024 / 1024 * 10) / 10} MB
          </a>
        </div>
      )}
    </div>
  );
}

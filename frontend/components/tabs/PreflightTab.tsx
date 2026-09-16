"use client";

import { useEffect, useRef, useState } from "react";
import { useApp } from "../AppProvider";
import { RenderPublic } from "../../lib/api";

export default function PreflightTab({
  clipId,
  render,
  onFixed,
}: {
  clipId: string;
  render: RenderPublic | null;
  onFixed: () => void;
}) {
  const { toast } = useApp();
  const [fixing, setFixing] = useState<string | null>(null);
  const simRef = useRef<HTMLCanvasElement>(null);

  const pf = render?.status === "done" ? render.preflight : null;

  useEffect(() => {
    const cv = simRef.current;
    if (!cv || !pf?.similarity_timeline?.length) return;
    const ctx = cv.getContext("2d")!;
    const W = (cv.width = cv.clientWidth * 2 || 600);
    const H = (cv.height = 120);
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#0d0d15";
    ctx.fillRect(0, 0, W, H);
    const data = pf.similarity_timeline;
    const max = 1;
    ctx.beginPath();
    data.forEach((v, i) => {
      const x = (i / (data.length - 1)) * W;
      const y = H - (v / max) * (H - 16) - 8;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.strokeStyle = "#8b5cf6";
    ctx.lineWidth = 3;
    ctx.stroke();
    ctx.lineTo(W, H);
    ctx.lineTo(0, H);
    ctx.fillStyle = "rgba(139,92,246,0.25)";
    ctx.fill();
    // 0.82 threshold
    const ty = H - (0.82 / max) * (H - 16) - 8;
    ctx.setLineDash([6, 6]);
    ctx.strokeStyle = "rgba(248,113,113,0.6)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, ty);
    ctx.lineTo(W, ty);
    ctx.stroke();
  }, [pf]);

  const score = pf?.score ?? null;
  const color = score == null ? "#71717a" : score >= 75 ? "#34d399" : score >= 50 ? "#fbbf24" : "#f87171";

  const fix = async (warningId: string) => {
    if (!render) return;
    setFixing(warningId);
    try {
      const r = await fetch(`/api/clips/${clipId}/renders/${render.id}/fix`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ warning_id: warningId }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || "Fix failed");
      toast("Fix applied — re-rendering with the correction", "success");
      onFixed();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setFixing(null);
    }
  };

  if (!render)
    return (
      <div className="flex h-full min-h-[200px] flex-col items-center justify-center text-center">
        <div className="text-4xl">🛡️</div>
        <p className="mt-3 text-sm font-semibold text-white">No render yet</p>
        <p className="mt-1 max-w-xs text-[11px] text-zinc-500">
          Render the clip from the Export tab — FairClip runs the Fair Use pre-flight automatically
          (unmodified-stretch, music level, similarity, 9:16, transformative elements).
        </p>
      </div>
    );

  if (render.status !== "done")
    return (
      <div className="flex h-full min-h-[200px] flex-col items-center justify-center text-center">
        <div className="pulse-soft text-4xl">⏳</div>
        <p className="mt-3 text-sm font-semibold text-white">{render.stage || "Rendering…"}</p>
        <p className="mt-1 text-[11px] text-zinc-500">{Math.round((render.progress || 0) * 100)}%</p>
      </div>
    );

  const rules = pf?.rules || {};
  const ruleRows = [
    ["r1_unmodified", "R1 · No unmodified stretch > 7s"],
    ["r2_music", "R2 · Music ≤ 25% for > 5s"],
    ["r3_transform", "R3 · ≥ 1 transformative element"],
    ["r4_vertical", "R4 · Output is 9:16 vertical"],
    ["r5_original_audio", "R5 · Audio is re-mixed"],
  ] as const;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-5 rounded-2xl border border-ink-600 bg-ink-850 p-4">
        <div className="relative h-24 w-24 shrink-0">
          <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90">
            <circle cx="50" cy="50" r="42" fill="none" stroke="#222234" strokeWidth="10" />
            <circle
              cx="50"
              cy="50"
              r="42"
              fill="none"
              stroke={color}
              strokeWidth="10"
              strokeLinecap="round"
              strokeDasharray={`${((score ?? 0) / 100) * 264} 264`}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-2xl font-extrabold text-white">{score ?? "–"}</span>
            <span className="text-[9px] uppercase tracking-wider text-zinc-500">score</span>
          </div>
        </div>
        <div>
          <p className="text-sm font-bold" style={{ color }}>
            {pf?.verdict || "—"}
          </p>
          <p className="mt-1 text-[11px] text-zinc-500">
            Frame similarity to source: {pf?.avg_similarity != null ? `${Math.round(pf.avg_similarity * 100)}%` : "—"}
          </p>
        </div>
      </div>

      <div>
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
          Frame similarity timeline (red = too close to source)
        </p>
        <canvas ref={simRef} className="w-full rounded-lg border border-ink-700" style={{ height: 60 }} />
      </div>

      <div className="space-y-1.5">
        {ruleRows.map(([k, label]) => {
          const pass = rules[k];
          return (
            <div key={k} className="flex items-center gap-2 text-xs">
              <span className={pass ? "text-emerald-400" : "text-red-400"}>{pass ? "✓" : "✗"}</span>
              <span className="text-zinc-300">{label}</span>
            </div>
          );
        })}
      </div>

      {pf?.warnings?.length ? (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Warnings & one-click fixes</p>
          {pf.warnings.map((w) => (
            <div key={w.id} className="flex items-center justify-between gap-3 rounded-xl border border-amber-800/40 bg-amber-950/20 p-3">
              <p className="text-[11px] leading-snug text-amber-200">{w.msg}</p>
              <button
                onClick={() => fix(w.id)}
                disabled={fixing === w.id}
                className="shrink-0 rounded-lg bg-accent px-3 py-1.5 text-[11px] font-bold text-white disabled:opacity-50"
              >
                {fixing === w.id ? "…" : `⚡ ${w.fix?.label || "Fix"}`}
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p className="rounded-xl border border-emerald-800/40 bg-emerald-950/20 p-3 text-[11px] text-emerald-300">
          No warnings — the clip passes all Fair Use checks. ✅
        </p>
      )}
    </div>
  );
}

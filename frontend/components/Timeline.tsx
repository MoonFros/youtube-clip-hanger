"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ClipPublic, JobPublic, Word, fmtTime } from "../lib/api";

const H = 176;

export default function Timeline({
  job,
  waveform,
  clips,
  selId,
  words,
  onSelect,
  onTrim,
}: {
  job: JobPublic;
  waveform: any;
  clips: ClipPublic[];
  selId: string | null;
  words: Word[];
  onSelect: (id: string) => void;
  onTrim: (start: number, end: number) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<null | { which: "start" | "end"; value: number }>(null);
  const [playhead, setPlayhead] = useState(0);

  const dur = Math.max(1, job.duration);

  // listen to playhead events from the phone preview
  useEffect(() => {
    const fn = (e: Event) => setPlayhead((e as CustomEvent).detail);
    window.addEventListener("fc-playhead", fn);
    return () => window.removeEventListener("fc-playhead", fn);
  }, []);

  const sel = clips.find((c) => c.id === selId) || null;
  const activeStart = drag?.which === "start" ? Math.min(drag.value, (sel?.end || dur) - 1) : sel?.start;
  const activeEnd = drag?.which === "end" ? Math.max(drag.value, (sel?.start || 0) + 1) : sel?.end;

  const draw = useCallback(() => {
    const cv = canvasRef.current, wrap = wrapRef.current;
    if (!cv || !wrap) return;
    const W = wrap.clientWidth;
    const dpr = window.devicePixelRatio || 1;
    cv.width = W * dpr;
    cv.height = H * dpr;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.fillStyle = "#0d0d15";
    ctx.fillRect(0, 0, W, H);

    const x = (t: number) => (t / dur) * W;

    // waveform (3 layers: dialogue / music / sfx)
    const w = waveform || {};
    const n = (w.rms && w.rms.length) || 100;
    const dt = w.dt || dur / n;
    const step = Math.max(1, Math.floor(n / (W / 2)));
    const strips = [
      { data: w.mid, color: "#e5e7eb", y0: 18, y1: 62 },
      { data: w.low, color: "#8b5cf6", y0: 66, y1: 110 },
      { data: w.high, color: "#fb923c", y0: 114, y1: 150 },
    ];
    for (const s of strips) {
      const data = s.data || [];
      ctx.fillStyle = s.color;
      for (let i = 0; i < data.length; i += step) {
        const v = Math.min(1, data[i] || 0);
        const hgt = Math.max(1.5, v * (s.y1 - s.y0) * 0.9);
        const px = x(i * dt);
        ctx.globalAlpha = 0.85;
        ctx.fillRect(px, (s.y0 + s.y1) / 2 - hgt / 2, Math.max(1.5, (step * dt / dur) * W - 0.6), hgt);
      }
      ctx.globalAlpha = 1;
    }

    // suggested clips
    for (const sc of job.suggested_clips || []) {
      ctx.fillStyle = "rgba(139,92,246,0.12)";
      ctx.fillRect(x(sc.start), H - 22, Math.max(4, x(sc.end - sc.start)), 14);
      ctx.fillStyle = "rgba(167,139,250,0.55)";
      ctx.fillRect(x(sc.start), H - 22, Math.max(4, x(sc.end - sc.start)), 2);
    }

    // scenes
    ctx.fillStyle = "rgba(255,255,255,0.35)";
    for (const s of job.scenes || []) ctx.fillRect(x(s) - 0.5, 8, 1, H - 34);

    // words ticks (transcript density)
    ctx.fillStyle = "rgba(34,211,238,0.5)";
    for (const wd of words) ctx.fillRect(x(wd.t0), H - 6, 1.5, 4);

    // other clips
    for (const c of clips) {
      if (c.id === selId) continue;
      ctx.fillStyle = "rgba(139,92,246,0.16)";
      ctx.strokeStyle = "rgba(139,92,246,0.5)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(x(c.start), 10, Math.max(6, x(c.end - c.start)), H - 46, 6);
      ctx.fill();
      ctx.stroke();
    }

    // selected clip
    if (sel) {
      const s = activeStart ?? sel.start;
      const e = activeEnd ?? sel.end;
      const xs = x(s), xe = x(e);
      ctx.fillStyle = "rgba(0,0,0,0.5)";
      ctx.fillRect(0, 0, xs, H);
      ctx.fillRect(xe, 0, W - xe, H);
      ctx.strokeStyle = "#8b5cf6";
      ctx.lineWidth = 2;
      ctx.strokeRect(xs, 8, xe - xs, H - 40);
      // handles
      for (const [hx, label] of [[xs, "⏮"], [xe, "⏭"]] as [number, string][]) {
        ctx.fillStyle = "#8b5cf6";
        ctx.beginPath();
        ctx.roundRect(hx - 6, 8, 12, H - 40, 4);
        ctx.fill();
        ctx.fillStyle = "#fff";
        ctx.font = "10px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(label, hx, 24);
      }
      // label
      ctx.fillStyle = "#fff";
      ctx.font = "600 11px sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(
        `${sel.name || "Clip"} · ${fmtTime(e - s)}`,
        xs + 10,
        22
      );
    }

    // playhead
    const px = x(playhead);
    ctx.fillStyle = "#22d3ee";
    ctx.fillRect(px - 1, 0, 2, H);
    ctx.beginPath();
    ctx.moveTo(px - 5, 0);
    ctx.lineTo(px + 5, 0);
    ctx.lineTo(px, 8);
    ctx.fill();

    // time ruler
    ctx.fillStyle = "rgba(255,255,255,0.4)";
    ctx.font = "9px sans-serif";
    ctx.textAlign = "left";
    const stepT = dur > 120 ? 30 : dur > 60 ? 10 : 5;
    for (let t = 0; t <= dur; t += stepT) {
      ctx.fillText(fmtTime(t), x(t) + 2, H - 4);
    }
  }, [job, waveform, clips, selId, sel, activeStart, activeEnd, words, dur, playhead]);

  useEffect(() => {
    draw();
    const onResize = () => draw();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [draw]);

  const tAt = (clientX: number) => {
    const wrap = wrapRef.current!;
    const r = wrap.getBoundingClientRect();
    return Math.min(dur, Math.max(0, ((clientX - r.left) / r.width) * dur));
  };

  const snap = (t: number) => {
    const near = (job.scenes || []).find((s) => Math.abs(s - t) < 0.15);
    return near ?? t;
  };

  const onPointerDown = (e: React.PointerEvent) => {
    const t = tAt(e.clientX);
    const wrap = wrapRef.current!;
    const r = wrap.getBoundingClientRect();
    const px = e.clientX - r.left;
    if (sel) {
      const xs = (sel.start / dur) * r.width;
      const xe = (sel.end / dur) * r.width;
      if (Math.abs(px - xs) < 12) {
        setDrag({ which: "start", value: t });
        (e.target as Element).setPointerCapture(e.pointerId);
        return;
      }
      if (Math.abs(px - xe) < 12) {
        setDrag({ which: "end", value: t });
        (e.target as Element).setPointerCapture(e.pointerId);
        return;
      }
    }
    // click: select clip under cursor or nearest
    const hit = clips.find((c) => t >= c.start && t <= c.end);
    if (hit) onSelect(hit.id);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag || !sel) return;
    let t = snap(tAt(e.clientX));
    if (drag.which === "start") t = Math.min(t, sel.end - 1);
    else t = Math.max(t, sel.start + 1);
    t = Math.min(dur - 0.5, Math.max(0, t));
    setDrag({ ...drag, value: t });
  };

  const onPointerUp = () => {
    if (!drag || !sel) return;
    const s = drag.which === "start" ? Math.min(drag.value, sel.end - 1) : sel.start;
    const en = drag.which === "end" ? Math.max(drag.value, sel.start + 1) : sel.end;
    if (Math.abs(s - sel.start) > 0.01 || Math.abs(en - sel.end) > 0.01) onTrim(s, en);
    setDrag(null);
  };

  return (
    <div ref={wrapRef} className="select-none">
      <canvas
        ref={canvasRef}
        style={{ width: "100%", height: H, touchAction: "none", cursor: drag ? "ew-resize" : "pointer" }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      />
      <div className="mt-1 flex items-center justify-between text-[10px] text-zinc-500">
        <span>
          <span className="text-zinc-300">■</span> dialogue ·{" "}
          <span className="text-accent-soft">■</span> music · <span className="text-orange-400">■</span> sfx
        </span>
        <span>drag the purple handles to trim · click to select a clip</span>
      </div>
    </div>
  );
}

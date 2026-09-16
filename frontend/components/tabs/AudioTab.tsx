"use client";

import { useEffect, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import { useApp } from "../AppProvider";
import { Analysis, ClipPublic, JobPublic, url } from "../../lib/api";

const LAYERS = [
  { id: "dialogue", label: "Dialogue", color: "#e5e7eb", icon: "🎙️", desc: "Speech — always kept clear", modes: ["keep", "mute"] },
  { id: "music", label: "Music", color: "#8b5cf6", icon: "🎵", desc: "Score & background music", modes: ["duck", "keep", "mute", "silence-gaps", "replace"] },
  { id: "sfx", label: "SFX / Impacts", color: "#fb923c", icon: "💥", desc: "Hits, whooshes, ambience", modes: ["keep", "duck", "mute"] },
];

const MODE_LABEL: Record<string, string> = {
  keep: "Keep at 100%",
  duck: "Duck to 15–20%",
  mute: "Mute",
  "silence-gaps": "0.5s micro-silence gaps",
  replace: "Replace with CC0 ambient",
};

export default function AudioTab({
  jobId,
  job,
  clip,
  analysis,
  onPatch,
  onTranscript,
}: {
  jobId: string;
  job: JobPublic;
  clip: ClipPublic;
  analysis: Analysis;
  onPatch: (p: any) => void;
  onTranscript: () => void;
}) {
  const { toast } = useApp();
  const boxRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const [solo, setSolo] = useState<string | null>(null);
  const [pasted, setPasted] = useState("");

  const stemsReady = analysis.stems?.status === "ready";

  useEffect(() => {
    return () => {
      wsRef.current?.destroy();
      wsRef.current = null;
    };
  }, []);

  const playSolo = async (layer: string) => {
    if (solo === layer) {
      wsRef.current?.destroy();
      wsRef.current = null;
      setSolo(null);
      return;
    }
    wsRef.current?.destroy();
    wsRef.current = null;
    if (!stemsReady) {
      toast("Layer separation still running — try again in a moment", "info");
      return;
    }
    const box = boxRef.current;
    if (!box) return;
    try {
      const ws = WaveSurfer.create({
        container: box,
        url: url(`/media/jobs/${jobId}/stems/${layer}`),
        waveColor: LAYERS.find((l) => l.id === layer)!.color + "66",
        progressColor: LAYERS.find((l) => l.id === layer)!.color,
        barWidth: 2,
        barGap: 1,
        height: 64,
        normalize: true,
      });
      wsRef.current = ws;
      setSolo(layer);
      ws.play();
      ws.on("finish", () => {
        setSolo(null);
        wsRef.current?.destroy();
        wsRef.current = null;
      });
    } catch (e: any) {
      setSolo(null);
      toast("Could not play layer preview", "error");
    }
  };

  const setLayer = (layer: string, patch: any) => {
    onPatch({ audio: { ...clip.audio, [layer]: { ...(clip.audio[layer] || { mode: "keep", gain: 1 }), ...patch } } });
  };

  return (
    <div className="space-y-5">
      <div>
        <h3 className="mb-2 text-sm font-semibold text-white">Stem separation</h3>
        <p className="mb-3 text-[11px] text-zinc-500">
          {stemsReady
            ? "Dialogue / Music / SFX separated (STFT + harmonic-percussive). Colors match the timeline."
            : "Separating audio layers in the background…"}
        </p>
        <div className="space-y-3">
          {LAYERS.map((l) => {
            const st = clip.audio[l.id] || { mode: l.id === "music" ? "duck" : "keep", gain: 1 };
            return (
              <div key={l.id} className="rounded-xl border border-ink-600 bg-ink-850 p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span>{l.icon}</span>
                    <div>
                      <p className="text-xs font-semibold" style={{ color: l.color }}>
                        {l.label}
                      </p>
                      <p className="text-[10px] text-zinc-500">{l.desc}</p>
                    </div>
                  </div>
                  <button
                    onClick={() => playSolo(l.id)}
                    className={`rounded-lg px-2.5 py-1.5 text-[11px] font-semibold transition ${
                      solo === l.id ? "bg-accent text-white" : "bg-ink-700 text-zinc-300 hover:text-white"
                    }`}
                  >
                    {solo === l.id ? "■ stop" : "▶ preview"}
                  </button>
                </div>
                <div className="mt-2 flex items-center gap-3">
                  <select
                    value={st.mode}
                    onChange={(e) => setLayer(l.id, { mode: e.target.value })}
                    className="flex-1 rounded-lg border border-ink-600 bg-ink-900 px-2 py-1.5 text-[11px] text-white outline-none"
                  >
                    {l.modes.map((m) => (
                      <option key={m} value={m}>
                        {MODE_LABEL[m] || m}
                      </option>
                    ))}
                  </select>
                  <label className="flex items-center gap-1.5 text-[10px] text-zinc-400">
                    gain
                    <input
                      type="range"
                      min={0}
                      max={1.5}
                      step={0.05}
                      value={st.gain}
                      onChange={(e) => setLayer(l.id, { gain: parseFloat(e.target.value) })}
                      className="w-20"
                    />
                    <span className="w-8 text-right tabular-nums">{Math.round(st.gain * 100)}%</span>
                  </label>
                </div>
              </div>
            );
          })}
        </div>
        <div ref={boxRef} className={solo ? "mt-3 rounded-lg bg-ink-950 p-2" : "hidden"} />
      </div>

      <div>
        <h3 className="mb-2 text-sm font-semibold text-white">Transcript</h3>
        {analysis.transcript.status === "ready" && (
          <div className="max-h-40 overflow-y-auto rounded-xl border border-ink-600 bg-ink-850 p-3 text-[11px] leading-relaxed text-zinc-300">
            {analysis.transcript.text}
            <p className="mt-2 text-[10px] text-zinc-500">
              {analysis.transcript.engine || "transcript"} · {analysis.transcript.words?.length || 0} words
            </p>
          </div>
        )}
        {analysis.transcript.status !== "ready" && (
          <div className="rounded-xl border border-ink-600 bg-ink-850 p-3">
            <p className="mb-2 text-[11px] text-zinc-400">
              No transcript available ({analysis.transcript.reason || "engine unavailable"}). Paste one
              below to enable word-level captions and the AI hook writer:
            </p>
            <textarea
              value={pasted}
              onChange={(e) => setPasted(e.target.value)}
              rows={4}
              placeholder="Paste the video's transcript…"
              className="w-full rounded-lg border border-ink-600 bg-ink-900 p-2 text-[11px] text-white placeholder-zinc-600 outline-none focus:border-accent"
            />
            <button
              disabled={pasted.trim().length < 20}
              onClick={async () => {
                try {
                  await fetch(url(`/api/jobs/${jobId}/transcript`), {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ text: pasted }),
                  });
                  toast("Transcript applied — captions & hooks unlocked", "success");
                  onTranscript();
                } catch (e: any) {
                  toast(e.message, "error");
                }
              }}
              className="mt-2 rounded-lg bg-accent px-3 py-1.5 text-[11px] font-semibold text-white disabled:opacity-40"
            >
              Apply transcript
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

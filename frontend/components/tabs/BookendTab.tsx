"use client";

import { useRef, useState } from "react";
import { useApp } from "../AppProvider";
import { ClipPublic } from "../../lib/api";

export default function BookendTab({
  jobId,
  clip,
  onPatch,
  onSaved,
}: {
  jobId: string;
  clip: ClipPublic;
  onPatch: (p: any) => void;
  onSaved: () => void;
}) {
  const { toast, health } = useApp();
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const [ttsUrls, setTtsUrls] = useState<{ intro?: string; outro?: string }>({});

  const be = clip.bookend || {
    enabled: false,
    style: "auto",
    intro_text: "",
    outro_text: "",
    fact: "",
    voice: "story",
    tts_status: "none",
  };

  const voices: Record<string, { label: string; desc: string }> =
    health?.tts_voices || { story: { label: "Story", desc: "" } };

  const generate = async () => {
    setBusy(true);
    try {
      const r = await fetch(`/api/clips/${clip.id}/bookend`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ style: be.style, voice: be.voice }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || "Generate failed");
      const j = await r.json();
      setTtsUrls(
        j.tts_audio || {
          intro: `/media/jobs/${jobId}/tts/tts_${clip.id}_intro.wav`,
          outro: `/media/jobs/${jobId}/tts/tts_${clip.id}_outro.wav`,
        }
      );
      toast("Bookend script generated", "success");
      onSaved();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const startMic = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      recRef.current = rec;
      chunksRef.current = [];
      rec.ondataavailable = (e) => chunksRef.current.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        const f = new File([blob], "intro_mic.webm", { type: "audio/webm" });
        const fd = new FormData();
        fd.append("mic", f);
        fd.append("style", be.style);
        fd.append("voice", "mic");
        try {
          const r = await fetch(`/api/clips/${clip.id}/bookend`, { method: "POST", body: fd });
          if (!r.ok) throw new Error((await r.json()).detail || "Mic upload failed");
          const j = await r.json();
          setTtsUrls(j.tts_audio || {});
          onPatch({ bookend: { ...be, voice: "mic" } });
          toast("Your voice recorded as the hook", "success");
          onSaved();
        } catch (e: any) {
          toast(e.message, "error");
        }
      };
      rec.start();
      setRecording(true);
      toast("Recording… 3s", "info");
      setTimeout(() => {
        if (recRef.current?.state === "recording") recRef.current.stop();
        setRecording(false);
      }, 3000);
    } catch (e: any) {
      toast("Microphone unavailable in this browser", "error");
    }
  };

  const playTts = (kind: "intro" | "outro") => {
    const url =
      ttsUrls[kind] || `/media/jobs/${jobId}/tts/tts_${clip.id}_${kind}.wav`;
    const a = new Audio(url);
    a.play().catch(() => toast("TTS not ready yet — generate the bookend first", "info"));
  };

  return (
    <div className="space-y-4">
      <label className="flex cursor-pointer items-center justify-between rounded-xl border border-ink-600 bg-ink-850 p-3">
        <div>
          <p className="text-sm font-semibold text-white">Breakdown bookend</p>
          <p className="text-[11px] text-zinc-500">
            AI-voiced hook card (first 3s) + CTA outro (last 3s) over the raw scene
          </p>
        </div>
        <input
          type="checkbox"
          checked={!!be.enabled}
          onChange={(e) => {
            onPatch({
              bookend: { ...be, enabled: e.target.checked },
              template: e.target.checked ? "breakdown_bookend" : clip.template,
            });
            if (e.target.checked) toast("Bookend enabled — switch template to use it fully", "info");
          }}
          className="h-5 w-9 appearance-none rounded-full bg-ink-600 checked:bg-accent"
        />
      </label>

      <div>
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Hook style</p>
        <div className="flex flex-wrap gap-1.5">
          {(Object.entries(health?.hook_styles || { auto: "Auto (best for scene)" }) as [string, string][]).map(
            ([k, v]) => (
            <button
              key={k}
              onClick={() => onPatch({ bookend: { ...be, style: k } })}
              className={`rounded-lg px-3 py-1.5 text-[11px] font-medium capitalize transition ${
                be.style === k ? "bg-accent text-white" : "bg-ink-700 text-zinc-300 hover:text-white"
              }`}
            >
              {k === "auto" ? "✨ auto" : k}
              <span className="ml-1 text-[9px] opacity-60">{v}</span>
            </button>
          ))}
        </div>
      </div>

      <div>
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
          Voice (hook + outro narration)
        </p>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(voices).map(([k, v]) => (
            <button
              key={k}
              onClick={() => onPatch({ bookend: { ...be, voice: k } })}
              className={`rounded-lg px-3 py-1.5 text-[11px] font-medium transition ${
                be.voice === k ? "bg-accent text-white" : "bg-ink-700 text-zinc-300 hover:text-white"
              }`}
            >
              {v.label}
            </button>
          ))}
          <button
            onClick={startMic}
            disabled={recording}
            className={`rounded-lg px-3 py-1.5 text-[11px] font-medium transition ${
              recording ? "bg-red-600 text-white" : be.voice === "mic" ? "bg-accent text-white" : "bg-ink-700 text-zinc-300 hover:text-white"
            }`}
          >
            {recording ? "● rec 3s" : "🎤 my mic"}
          </button>
          <button
            onClick={() => onPatch({ bookend: { ...be, voice: "off" } })}
            className={`rounded-lg px-3 py-1.5 text-[11px] font-medium transition ${
              be.voice === "off" ? "bg-accent text-white" : "bg-ink-700 text-zinc-300 hover:text-white"
            }`}
          >
            off
          </button>
        </div>
      </div>

      <button
        onClick={generate}
        disabled={busy || !be.enabled}
        className="w-full rounded-xl bg-gradient-to-r from-accent to-accent-dim px-4 py-3 text-sm font-bold text-white shadow-glow disabled:opacity-40"
      >
        {busy ? "Writing script + TTS…" : "🪄 Generate hook & outro"}
      </button>

      {(be.intro_text || be.outro_text || be.fact) && (
        <div className="space-y-2 rounded-xl border border-ink-600 bg-ink-850 p-3">
          {be.fact && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-zinc-500">Fact card (reaction frame)</p>
              <p className="text-xs text-cyan-300">{be.fact}</p>
            </div>
          )}
          {be.intro_text && (
            <div>
              <div className="flex items-center justify-between">
                <p className="text-[10px] uppercase tracking-wider text-zinc-500">Hook (0–3s)</p>
                <button onClick={() => playTts("intro")} className="text-[10px] text-accent-soft underline">
                  ▶ play
                </button>
              </div>
              <p className="text-xs leading-snug text-white">{be.intro_text}</p>
            </div>
          )}
          {be.outro_text && (
            <div>
              <div className="flex items-center justify-between">
                <p className="text-[10px] uppercase tracking-wider text-zinc-500">Outro CTA (last 3s)</p>
                <button onClick={() => playTts("outro")} className="text-[10px] text-accent-soft underline">
                  ▶ play
                </button>
              </div>
              <p className="text-xs leading-snug text-white">{be.outro_text}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

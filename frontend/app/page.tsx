"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { useApp } from "../components/AppProvider";
import { api, url } from "../lib/api";

const TEMPLATES = [
  { emoji: "🎬", name: "Cinematic Zoom", desc: "Slow push-in, cinematic grade, micro-cuts" },
  { emoji: "📊", name: "Split Screen", desc: "Zoomed top + live waveform & captions" },
  { emoji: "🌩️", name: "Caption Storm", desc: "Punchy bouncing words, keyword highlights" },
  { emoji: "🔮", name: "Reaction Frame", desc: "Floating window over blurred scene" },
  { emoji: "✨", name: "Minimal Clean", desc: "Just the scene, speed-ramped & clean" },
  { emoji: "🎙️", name: "Breakdown Bookend", desc: "AI-voiced hook intro + CTA outro" },
];

export default function Landing() {
  const router = useRouter();
  const { toast, health } = useApp();
  const [tab, setTab] = useState<"demo" | "upload" | "url" | "link">("demo");
  const [linkUrl, setLinkUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [plan, setPlan] = useState<"free" | "pro">("free");

  useEffect(() => {
    if (health) setPlan((health.plan as any) || "free");
  }, [health]);

  const demoState: string = health?.demo_error
    ? "error"
    : health?.demo_generating
      ? "generating"
      : health?.demo_ready
        ? "ready"
        : health
          ? "none"
          : "unknown";

  const start = async () => {
    setBusy(true);
    try {
      let source: any;
      if (tab === "demo") source = { type: "demo" };
      else if (tab === "url") source = { type: "url", url: linkUrl };
      else if (tab === "link") source = { type: "link", url: linkUrl };
      else {
        if (!file) throw new Error("Choose a video file first");
        source = { type: "upload" };
      }
      const j = await api<{ job_id: string }>("/api/jobs", { method: "POST", body: JSON.stringify({ source }) });
      if (tab === "upload") {
        const fd = new FormData();
        fd.append("file", file);
        const r = await fetch(url(`/api/jobs/${j.job_id}/upload`), { method: "POST", body: fd });
        if (!r.ok) throw new Error("Upload failed: " + (await r.text()));
      }
      router.push(`/job/${j.job_id}`);
    } catch (e: any) {
      toast(e.message || "Could not start the job", "error");
      setBusy(false);
    }
  };

  const demoButton = () => {
    if (demoState === "generating")
      return (
        <span className="pulse-soft text-xs text-amber-300">
          Crafting the demo video (first run ~1 min)…
        </span>
      );
    return (
      <button
        onClick={start}
        disabled={busy}
        className="rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent-soft disabled:opacity-50"
      >
        {busy ? "Starting…" : "Clip the demo →"}
      </button>
    );
  };

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col px-6 py-8">
      <header className="mb-10 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent/25 text-lg">✂️</div>
          <span className="text-lg font-bold tracking-tight text-white">FairClip</span>
          <span className="ml-2 rounded-full border border-ink-600 px-2 py-0.5 text-[11px] text-zinc-400">
            AI Fair Use clipping
          </span>
        </div>
        <div className="flex items-center gap-1 rounded-xl border border-ink-600 bg-ink-900 p-1 text-xs">
          {(["free", "pro"] as const).map((p) => (
            <button
              key={p}
              onClick={() => {
                setPlan(p);
                api("/api/settings", { method: "PUT", body: JSON.stringify({ plan: p }) }).catch(() => {});
              }}
              className={`rounded-lg px-3 py-1.5 font-medium capitalize transition ${
                plan === p ? "bg-accent text-white" : "text-zinc-400 hover:text-white"
              }`}
            >
              {p === "pro" ? `Pro $9/mo` : "Free"}
            </button>
          ))}
        </div>
      </header>

      <div className="mb-10 max-w-2xl">
        <motion.h1
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-4xl font-extrabold leading-tight tracking-tight text-white md:text-5xl"
        >
          Turn long videos into <span className="bg-gradient-to-r from-accent-soft to-cy bg-clip-text text-transparent">viral vertical clips</span>
        </motion.h1>
        <motion.p
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="mt-4 text-base leading-relaxed text-zinc-400"
        >
          FairClip finds the best 15–60 second moments, reframes them for Shorts / Reels / TikTok,
          separates dialogue from music, adds dynamic captions — and applies the Fair Use
          transformations (reframe, micro-cuts, ducking, captions) automatically.
        </motion.p>
      </div>

      <div className="grid flex-1 gap-6 md:grid-cols-[1.2fr_1fr]">
        {/* input card */}
        <motion.section
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15 }}
          className="rounded-2xl border border-ink-600 bg-ink-900 p-6"
        >
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-zinc-400">
            1 · Your video
          </h2>
          <div className="mb-4 flex flex-wrap gap-1 rounded-xl bg-ink-850 p-1 text-sm">
            {(
              [
                ["demo", "🎬 Demo video"],
                ["upload", "⬆️ Upload"],
                ["url", "🔗 YouTube URL"],
                ["link", "🌐 Direct link"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={`rounded-lg px-3 py-2 font-medium transition ${
                  tab === id ? "bg-ink-600 text-white" : "text-zinc-400 hover:text-white"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {tab === "demo" && (
            <div className="rounded-xl border border-ink-700 bg-ink-850 p-5">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="font-semibold text-white">“Founders & Failures” — 100s demo</p>
                  <p className="mt-1 text-xs text-zinc-400">
                    Synthetic demo video: 10 shots, AI voiceover, music bed, SFX. Generated
                    automatically by FairClip on first use.
                  </p>
                </div>
                {demoButton()}
              </div>
              {demoState === "error" && (
                <p className="mt-3 text-xs text-red-400">Demo generation failed — try upload instead.</p>
              )}
            </div>
          )}

          {tab === "upload" && (
            <div
              onClick={() => fileRef.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                const f = e.dataTransfer.files?.[0];
                if (f) setFile(f);
              }}
              className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center transition ${
                file ? "border-accent bg-accent/5" : "border-ink-600 bg-ink-850 hover:border-accent/60"
              }`}
            >
              <input
                ref={fileRef}
                type="file"
                accept="video/mp4,video/x-matroska,video/webm,video/quicktime"
                className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
              />
              <div className="text-3xl">🎞️</div>
              <p className="mt-2 text-sm font-medium text-white">
                {file ? file.name : "Drop a .mp4 / .mkv / .webm here or click to browse"}
              </p>
              <p className="mt-1 text-xs text-zinc-500">Processed locally in your browser session — max ~200 MB</p>
              {file && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setFile(null);
                  }}
                  className="mt-3 text-xs text-zinc-400 underline"
                >
                  choose another file
                </button>
              )}
            </div>
          )}
          {tab === "upload" && (
            <div className="mt-3">
              <button
                onClick={start}
                disabled={busy || !file}
                className="w-full rounded-xl bg-gradient-to-r from-accent to-cy px-4 py-3 text-sm font-bold text-white shadow-glow transition hover:brightness-110 disabled:opacity-40"
              >
                {busy ? `Uploading ${file?.name || ""}…` : "⚡ Clip this video →"}
              </button>
              {file && (
                <p className="mt-2 text-center text-[11px] text-zinc-500">
                  {file.name} · {(file.size / 1024 / 1024).toFixed(1)} MB — analysis starts after upload
                </p>
              )}
            </div>
          )}

          {(tab === "url" || tab === "link") && (
            <div className="rounded-xl border border-ink-700 bg-ink-850 p-5">
              <input
                value={linkUrl}
                onChange={(e) => setLinkUrl(e.target.value)}
                placeholder={tab === "url" ? "https://youtube.com/watch?v=…" : "https://example.com/talk.mp4"}
                className="w-full rounded-lg border border-ink-600 bg-ink-900 px-3 py-2.5 text-sm text-white placeholder-zinc-600 outline-none focus:border-accent"
              />
              <p className="mt-2 text-xs text-zinc-500">
                {tab === "url"
                  ? "YouTube links are downloaded with yt-dlp when the network allows it."
                  : "Direct .mp4/.mkv URLs are downloaded straight to the editor."}
              </p>
              <button
                onClick={start}
                disabled={busy || !linkUrl.trim()}
                className="mt-4 rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent-soft disabled:opacity-40"
              >
                {busy ? "Fetching…" : "Fetch video →"}
              </button>
            </div>
          )}
        </motion.section>

        {/* right column */}
        <div className="flex flex-col gap-6">
          <motion.section
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="rounded-2xl border border-ink-600 bg-ink-900 p-6"
          >
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-zinc-400">
              2 · Six Fair Use templates
            </h2>
            <div className="grid grid-cols-2 gap-2">
              {TEMPLATES.map((t) => (
                <div key={t.name} className="rounded-xl border border-ink-700 bg-ink-850 p-3">
                  <div className="text-xl">{t.emoji}</div>
                  <p className="mt-1 text-xs font-semibold text-white">{t.name}</p>
                  <p className="mt-0.5 text-[11px] leading-snug text-zinc-500">{t.desc}</p>
                </div>
              ))}
            </div>
          </motion.section>

          <motion.section
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.25 }}
            className="rounded-2xl border border-ink-600 bg-ink-900 p-6"
          >
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-zinc-400">
              3 · Audio intelligence
            </h2>
            <ul className="space-y-2 text-sm text-zinc-300">
              <li className="flex gap-2"><span>🎙️</span> Dialogue kept at 100% — always</li>
              <li className="flex gap-2"><span>🎵</span> Music auto-ducked to 15–20% (or silenced in gaps)</li>
              <li className="flex gap-2"><span>💥</span> SFX & impacts preserved</li>
              <li className="flex gap-2"><span>🎛️</span> Per-layer waveform with manual override</li>
            </ul>
          </motion.section>
        </div>
      </div>

      <footer className="mt-10 border-t border-ink-800 pt-4 text-center text-[11px] leading-relaxed text-zinc-600">
        FairClip is a creative tool, not legal advice. Fair use depends on many facts (17 U.S.C. § 107).
        Get permission from copyright holders when possible.
      </footer>
    </div>
  );
}

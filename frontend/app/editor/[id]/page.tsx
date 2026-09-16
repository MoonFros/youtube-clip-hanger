"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, Analysis, ClipPublic, JobPublic, RenderPublic, fmtTime } from "../../../lib/api";
import PhonePreview from "../../../components/PhonePreview";
import Timeline from "../../../components/Timeline";
import TemplatesTab from "../../../components/tabs/TemplatesTab";
import AudioTab from "../../../components/tabs/AudioTab";
import BookendTab from "../../../components/tabs/BookendTab";
import PreflightTab from "../../../components/tabs/PreflightTab";
import ExportTab from "../../../components/tabs/ExportTab";

type Tab = "templates" | "audio" | "bookend" | "preflight" | "export";

export default function EditorPage() {
  const { id } = useParams<{ id: string }>();
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [clips, setClips] = useState<ClipPublic[]>([]);
  const [selId, setSelId] = useState<string | null>(null);
  const [renders, setRenders] = useState<RenderPublic[]>([]);
  const [tab, setTab] = useState<Tab>("templates");
  const [err, setErr] = useState("");

  const sel = useMemo(() => clips.find((c) => c.id === selId) || null, [clips, selId]);
  const selRender = useMemo(
    () => renders.find((r) => r.clip_id === selId) || null,
    [renders, selId]
  );

  const loadAnalysis = useCallback(async () => {
    try {
      const a = await api<Analysis>(`/api/jobs/${id}/analysis`);
      setAnalysis(a);
    } catch (e: any) {
      setErr(e.message || "Could not load analysis");
    }
  }, [id]);

  const loadClips = useCallback(async () => {
    const list = await api<ClipPublic[]>(`/api/jobs/${id}/clips`);
    setClips(list);
    setSelId((cur) => cur && list.some((c) => c.id === cur) ? cur : list[0]?.id || null);
  }, [id]);

  const loadRenders = useCallback(async (cid: string) => {
    const list = await api<RenderPublic[]>(`/api/clips/${cid}/renders`);
    setRenders(list);
  }, []);

  // initial load
  useEffect(() => {
    loadAnalysis().then(loadClips).then(() => {});
  }, [loadAnalysis, loadClips]);

  // ensure at least one clip exists
  useEffect(() => {
    if (analysis && analysis.job.status === "ready" && clips.length === 0 && !err) {
      const s = analysis.job.suggested_clips[0];
      if (s) {
        api(`/api/jobs/${id}/clips`, {
          method: "POST",
          body: JSON.stringify({ start: s.start, end: s.end, name: s.label }),
        })
          .then(() => loadClips())
          .catch((e) => setErr(e.message));
      }
    }
  }, [analysis, clips.length, id, loadClips, err]);

  // poll renders while one is running
  useEffect(() => {
    const running = renders.find((r) => r.status === "running");
    if (!running) return;
    const iv = setInterval(async () => {
      try {
        const list = await api<RenderPublic[]>(`/api/clips/${running.clip_id}/renders`);
        setRenders(list);
      } catch {}
    }, 1200);
    return () => clearInterval(iv);
  }, [renders]);

  if (err)
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="rounded-2xl border border-ink-600 bg-ink-900 p-8 text-center">
          <p className="text-red-400">{err}</p>
          <Link href="/" className="mt-4 inline-block rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-white">
            Back to start
          </Link>
        </div>
      </div>
    );

  if (!analysis)
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-zinc-500">
        <span className="pulse-soft">Loading editor…</span>
      </div>
    );

  const job = analysis.job;
  const runningRender = renders.find((r) => r.status === "running");

  const patchClip = (patch: Record<string, any>) => {
    if (!sel) return;
    api(`/api/clips/${sel.id}`, { method: "PATCH", body: JSON.stringify(patch) }).then(() => loadClips()).catch(
      (e) => console.error(e)
    );
  };

  const tabs: [Tab, string, string][] = [
    ["templates", "🎨", "Templates"],
    ["audio", "🎚️", "Audio"],
    ["bookend", "🎙️", "Bookend"],
    ["preflight", "🛡️", "Pre-flight"],
    ["export", "📤", "Export"],
  ];

  return (
    <div className="mx-auto flex h-screen max-w-[1700px] flex-col px-3 py-3 md:px-5">
      {/* top bar */}
      <header className="mb-3 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <Link href="/" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent/25 text-base">
            ✂️
          </Link>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-white">{job.name || "Untitled job"}</p>
            <p className="text-[11px] text-zinc-500">
              {fmtTime(job.duration)} · {job.width}×{job.height} @ {job.fps}fps
              {job.letterbox.top > 2 && " · letterbox auto-removed"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {sel && (
            <span className="hidden rounded-full border border-ink-600 bg-ink-900 px-3 py-1 text-[11px] text-zinc-300 sm:block">
              {sel.name || "Clip"} · {fmtTime(sel.duration)} · {sel.template}
            </span>
          )}
          <Link
            href="/"
            className="rounded-lg border border-ink-600 bg-ink-900 px-3 py-1.5 text-xs text-zinc-300 transition hover:text-white"
          >
            + New video
          </Link>
        </div>
      </header>

      {/* main grid */}
      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(300px,380px)_1fr]">
        {/* left: preview + timeline */}
        <div className="flex min-h-0 flex-col gap-3">
          {sel && (
            <PhonePreview
              jobId={id}
              job={job}
              clip={sel}
              words={analysis.transcript.words || []}
              playhead={(t) => window.dispatchEvent(new CustomEvent("fc-playhead", { detail: t }))}
            />
          )}
          {sel && (
            <Timeline
              job={job}
              waveform={analysis.waveform}
              clips={clips}
              selId={selId}
              words={analysis.transcript.words || []}
              onSelect={setSelId}
              onTrim={(start, end) => patchClip({ start, end })}
            />
          )}
          {/* clips strip */}
          <div className="flex gap-2 overflow-x-auto pb-1">
            {clips.map((c, i) => (
              <button
                key={c.id}
                onClick={() => {
                  setSelId(c.id);
                  loadRenders(c.id);
                }}
                className={`shrink-0 rounded-xl border px-3 py-2 text-left text-xs transition ${
                  c.id === selId
                    ? "border-accent bg-accent/10 text-white"
                    : "border-ink-600 bg-ink-900 text-zinc-400 hover:text-white"
                }`}
              >
                <span className="font-semibold">Clip {i + 1}</span>
                <span className="ml-2 text-zinc-500">
                  {fmtTime(c.start)}–{fmtTime(c.end)}
                </span>
                {c.renders.length > 0 && <span className="ml-2 text-emerald-400">●</span>}
              </button>
            ))}
            <button
              onClick={async () => {
                try {
                  const start = 0;
                  const end = Math.min(30, Math.max(5, job.duration - 0.5));
                  await api(`/api/jobs/${id}/clips`, {
                    method: "POST",
                    body: JSON.stringify({ start, end, name: "New clip" }),
                  });
                  await loadClips();
                } catch (e: any) {
                  console.error(e);
                }
              }}
              className="shrink-0 rounded-xl border border-dashed border-ink-600 px-3 py-2 text-xs text-zinc-500 hover:text-white"
            >
              + Add
            </button>
          </div>
        </div>

        {/* right: panels */}
        <div className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-ink-600 bg-ink-900">
          <div className="flex gap-1 border-b border-ink-700 p-2">
            {tabs.map(([tid, emoji, label]) => (
              <button
                key={tid}
                onClick={() => setTab(tid)}
                className={`rounded-lg px-3 py-2 text-xs font-medium transition ${
                  tab === tid ? "bg-ink-600 text-white" : "text-zinc-400 hover:text-white"
                }`}
              >
                <span className="mr-1">{emoji}</span>
                <span className="hidden sm:inline">{label}</span>
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {!sel && <p className="text-sm text-zinc-500">Select a clip to start editing.</p>}
            {sel && tab === "templates" && (
              <TemplatesTab job={job} clip={sel} templates={analysis.templates} onPatch={patchClip} />
            )}
            {sel && tab === "audio" && (
              <AudioTab jobId={id} job={job} clip={sel} analysis={analysis} onPatch={patchClip} onTranscript={loadAnalysis} />
            )}
            {sel && tab === "bookend" && (
              <BookendTab jobId={id} clip={sel} onPatch={patchClip} onSaved={() => loadClips().then(() => loadRenders(sel.id))} />
            )}
            {sel && tab === "preflight" && (
              <PreflightTab
                clipId={sel.id}
                render={selRender}
                onFixed={() => loadRenders(sel.id)}
              />
            )}
            {sel && tab === "export" && (
              <ExportTab jobId={id} clip={sel} renders={renders} running={!!runningRender} onRendered={() => loadRenders(sel.id)} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

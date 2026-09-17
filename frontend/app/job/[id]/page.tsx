"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { motion } from "framer-motion";
import { api, JobPublic, STAGE_LABELS } from "../../../lib/api";

/** Statuses that mean "this job is over, stop polling". */
const FINAL = ["ready", "error", "failed", "cancelled"];

function fmtClock(sec: number): string {
  sec = Math.max(0, Math.floor(sec));
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}

export default function JobPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [job, setJob] = useState<JobPublic | null>(null);
  const [error, setError] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [stalledFor, setStalledFor] = useState(0);
  const [cancelling, setCancelling] = useState(false);
  const lastChange = useRef<number>(Date.now());
  const lastProgress = useRef<string>("");

  const tick = useCallback(async () => {
    try {
      const j = await api<JobPublic>(`/api/jobs/${id}`);
      setJob(j);
      const stamp = `${j.status}:${j.stage}:${j.progress}`;
      if (stamp !== lastProgress.current) {
        lastProgress.current = stamp;
        lastChange.current = Date.now();
      }
      if (j.status === "ready") {
        setTimeout(() => router.replace(`/editor/${id}`), 350);
      } else if (j.status === "error" || j.status === "failed") {
        setError(j.error || "The job failed.");
      } else if (j.status === "cancelled") {
        setError("Cancelled.");
      }
    } catch (e: any) {
      setError(e.message || "Lost connection to the backend");
    }
  }, [id, router]);

  useEffect(() => {
    let stop = false;
    const run = async () => {
      if (!stop) await tick();
    };
    run();
    const iv = setInterval(run, 1500);
    const clock = setInterval(() => {
      if (job) setElapsed(Date.now() / 1000 - job.created);
      setStalledFor((Date.now() - lastChange.current) / 1000);
    }, 500);
    return () => {
      stop = true;
      clearInterval(iv);
      clearInterval(clock);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);

  const cancel = async () => {
    setCancelling(true);
    try {
      await api(`/api/jobs/${id}`, { method: "DELETE" });
    } catch {
      /* the poller will show whatever happened */
    }
  };

  const pct = job ? Math.round((job.progress || 0) * 100) : 0;
  const done = job ? FINAL.includes(job.status) : false;
  const stageLabel = job
    ? STAGE_LABELS[job.stage] || job.stage || "Starting…"
    : "Connecting…";

  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} className="w-full max-w-lg">
        <div className="rounded-2xl border border-ink-600 bg-ink-900 p-8">
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-accent/20 text-2xl">
              {error ? "⚠️" : job?.status === "ready" ? "✅" : "🧠"}
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-lg font-bold text-white">
                {error ? "Something went wrong" : job?.status === "ready" ? "Ready" : "Analyzing your video"}
              </h1>
              <p className="truncate text-xs text-zinc-500">
                {job?.name || "…"}
                {job?.duration ? ` · ${Math.round(job.duration)}s` : ""}
                {elapsed > 1 ? ` · ${fmtClock(elapsed)} elapsed` : ""}
              </p>
            </div>
          </div>

          {error ? (
            <>
              <p className="whitespace-pre-wrap rounded-xl border border-red-900/60 bg-red-950/40 p-3 text-sm text-red-200">
                {error}
              </p>
              <div className="mt-5 flex gap-2">
                <button
                  onClick={() => router.push("/")}
                  className="rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-soft"
                >
                  Back to start
                </button>
                <button
                  onClick={() => {
                    setError("");
                    lastChange.current = Date.now();
                    tick();
                  }}
                  className="rounded-xl border border-ink-600 px-4 py-2 text-sm text-zinc-300 hover:text-white"
                >
                  Keep watching
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="text-sm text-zinc-300">{stageLabel}</p>
              {job?.detail ? (
                <p className="mt-1 font-mono text-xs text-zinc-500">{job.detail}</p>
              ) : null}

              <div className="mt-5">
                <div className="h-2 w-full overflow-hidden rounded-full bg-ink-700">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-accent to-cy transition-all duration-500"
                    style={{ width: `${Math.max(3, pct)}%` }}
                  />
                </div>
                <div className="mt-2 flex justify-between text-xs text-zinc-500">
                  <span>{pct}%</span>
                  <span className="capitalize">{job?.status || "queued"}</span>
                </div>
              </div>

              {stalledFor > 25 && (
                <p className="mt-4 rounded-xl border border-amber-900/50 bg-amber-950/30 p-3 text-xs text-amber-200">
                  No progress for {Math.round(stalledFor)}s. Long videos take a while
                  (download → transcode → audio analysis → transcription); the numbers
                  above update as each step advances. Everything is on-device, so a slow
                  CPU is the usual cause — you can cancel and try a shorter clip or a
                  720p source.
                </p>
              )}

              {!done && (
                <button
                  onClick={cancel}
                  disabled={cancelling}
                  className="mt-5 rounded-xl border border-ink-600 px-4 py-2 text-sm text-zinc-300 hover:border-red-800 hover:text-red-200 disabled:opacity-50"
                >
                  {cancelling ? "Cancelling…" : "Cancel job"}
                </button>
              )}
            </>
          )}
        </div>

        <p className="mt-4 text-center text-xs text-zinc-600">
          Tip: the backend log prints a line per stage — if a stage is failing it says why.
        </p>
      </motion.div>
    </div>
  );
}

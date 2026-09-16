"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { motion } from "framer-motion";
import { api, JobPublic, STAGE_LABELS } from "../../../lib/api";

export default function JobPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [job, setJob] = useState<JobPublic | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const j = await api<JobPublic>(`/api/jobs/${id}`);
        if (stop) return;
        setJob(j);
        if (j.status === "ready") {
          setTimeout(() => !stop && router.replace(`/editor/${id}`), 350);
        } else if (j.status === "error") {
          setError(j.error || "Job failed");
        }
      } catch (e: any) {
        if (!stop) setError(e.message || "Lost connection to the backend");
      }
    };
    tick();
    const iv = setInterval(tick, 1500);
    return () => {
      stop = true;
      clearInterval(iv);
    };
  }, [id, router]);

  const pct = job ? Math.round((job.progress || 0) * 100) : 0;

  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} className="w-full max-w-md">
        <div className="rounded-2xl border border-ink-600 bg-ink-900 p-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/20 text-2xl">
            {error ? "⚠️" : "🧠"}
          </div>
          <h1 className="text-xl font-bold text-white">
            {error ? "Something went wrong" : "Analyzing your video"}
          </h1>
          <p className="mt-2 text-sm text-zinc-400">
            {error || (job ? STAGE_LABELS[job.stage] || job.stage || "Working…" : "Connecting…")}
          </p>
          {!error && (
            <div className="mt-6">
              <div className="h-2 w-full overflow-hidden rounded-full bg-ink-700">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-accent to-cy transition-all duration-500"
                  style={{ width: `${Math.max(4, pct)}%` }}
                />
              </div>
              <p className="mt-2 text-xs text-zinc-500">{pct}%</p>
            </div>
          )}
          {error && (
            <button
              onClick={() => router.push("/")}
              className="mt-6 rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-soft"
            >
              Back to start
            </button>
          )}
        </div>
      </motion.div>
    </div>
  );
}

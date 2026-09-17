"use client";
import { useEffect, useState } from "react";

type Job = {
  id: string;
  url: string;
  start_time: string;
  end_time: string;
  status: "queued" | "processing" | "completed" | "failed";
  created_at: string;
  clip_path?: string;
  title?: string;
};

export default function Home() {
  const [health, setHealth] = useState<any>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [url, setUrl] = useState("");
  const [start, setStart] = useState("00:00:00");
  const [end, setEnd] = useState("00:00:10");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchHealth = async () => {
    try {
      const res = await fetch("/api/health");
      if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
      const data = await res.json();
      setHealth(data);
      setError(null);
    } catch (e: any) {
      setError(e.message);
      setHealth(null);
    }
  };

  const fetchJobs = async () => {
    try {
      const res = await fetch("/api/jobs");
      if (!res.ok) throw new Error(`Jobs fetch failed: ${res.status}`);
      const data = await res.json();
      setJobs(data);
    } catch (e: any) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchHealth();
    fetchJobs();
    const interval = setInterval(fetchJobs, 3000);
    return () => clearInterval(interval);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          start_time: start,
          end_time: end,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "Failed to create job");
      }
      const job = await res.json();
      setJobs((prev) => [job, ...prev]);
      setUrl("");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100 p-6">
      <div className="max-w-5xl mx-auto space-y-8">
        <header className="flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">YouTube Clip Hanger ✂️</h1>
            <p className="text-zinc-400 mt-1">Clip YouTube videos by timestamp. Backend + Frontend fixed.</p>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <span className={`w-2 h-2 rounded-full ${health ? "bg-green-500" : "bg-red-500"} animate-pulse`} />
            <span className="text-zinc-400">
              {health ? `API OK (${health.status})` : "API disconnected"}
            </span>
            <button onClick={fetchHealth} className="ml-2 px-3 py-1 bg-zinc-800 rounded hover:bg-zinc-700">Retry</button>
          </div>
        </header>

        {error && (
          <div className="bg-red-950 border border-red-800 text-red-200 p-4 rounded">
            <p className="font-mono text-sm">{error}</p>
            <p className="text-xs mt-2 text-red-300">
              Fix: Make sure backend is running on 0.0.0.0:8000. Run <code className="bg-red-900 px-1 rounded">npm run dev:all</code> or start backend separately with <code className="bg-red-900 px-1 rounded">python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload</code>
            </p>
          </div>
        )}

        <section className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
          <h2 className="text-lg font-semibold mb-4">Create Clip</h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-sm text-zinc-400">YouTube URL</label>
              <input
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://www.youtube.com/watch?v=..."
                className="w-full mt-1 px-4 py-2.5 bg-zinc-950 border border-zinc-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-white/20"
                required
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm text-zinc-400">Start (HH:MM:SS or seconds)</label>
                <input
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                  className="w-full mt-1 px-4 py-2.5 bg-zinc-950 border border-zinc-800 rounded-lg"
                />
              </div>
              <div>
                <label className="text-sm text-zinc-400">End (HH:MM:SS or seconds)</label>
                <input
                  value={end}
                  onChange={(e) => setEnd(e.target.value)}
                  className="w-full mt-1 px-4 py-2.5 bg-zinc-950 border border-zinc-800 rounded-lg"
                />
              </div>
            </div>
            <button
              disabled={loading}
              className="px-5 py-2.5 bg-white text-black font-medium rounded-lg hover:bg-zinc-200 disabled:opacity-50"
            >
              {loading ? "Creating..." : "Create Clip"}
            </button>
          </form>
        </section>

        <section className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Jobs</h2>
            <button onClick={fetchJobs} className="text-sm px-3 py-1 bg-zinc-800 rounded hover:bg-zinc-700">Refresh</button>
          </div>
          {jobs.length === 0 ? (
            <p className="text-zinc-500 text-sm">No jobs yet. Create one above.</p>
          ) : (
            <div className="space-y-3">
              {jobs.map((job) => (
                <div key={job.id} className="flex justify-between items-center p-4 bg-zinc-950 border border-zinc-800 rounded-lg">
                  <div className="min-w-0">
                    <p className="font-medium truncate">{job.title || job.url}</p>
                    <p className="text-xs text-zinc-500 font-mono truncate">{job.url} | {job.start_time} → {job.end_time}</p>
                    <p className="text-xs text-zinc-600 mt-1">{new Date(job.created_at).toLocaleString()}</p>
                  </div>
                  <div className="ml-4 flex flex-col items-end gap-1">
                    <span className={`text-xs px-2 py-1 rounded-full ${
                      job.status === "completed" ? "bg-green-950 text-green-300 border border-green-800" :
                      job.status === "failed" ? "bg-red-950 text-red-300 border border-red-800" :
                      job.status === "processing" ? "bg-yellow-950 text-yellow-300 border border-yellow-800" :
                      "bg-zinc-800 text-zinc-400"
                    }`}>{job.status}</span>
                    {job.clip_path && <a href={job.clip_path} target="_blank" className="text-xs text-white underline">Download</a>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
          <h3 className="font-semibold mb-2">How this fixes your ECONNREFUSED error</h3>
          <ul className="list-disc list-inside text-sm text-zinc-400 space-y-1">
            <li><code className="bg-zinc-800 px-1 rounded">next.config.mjs</code> now has <code className="bg-zinc-800 px-1 rounded">rewrites()</code> proxying <code className="bg-zinc-800 px-1 rounded">/api/*</code> to <code className="bg-zinc-800 px-1 rounded">http://127.0.0.1:8000/api/*</code></li>
            <li>Frontend dev server binds to <code className="bg-zinc-800 px-1 rounded">0.0.0.0:3000</code> (not 127.0.0.1) so Arena preview <code className="bg-zinc-800 px-1 rounded">https://3000-*.e2b.app</code> can reach it</li>
            <li>Backend binds to <code className="bg-zinc-800 px-1 rounded">0.0.0.0:8000</code> - required, otherwise frontend can't connect</li>
            <li>You must run BOTH services: <code className="bg-zinc-800 px-1 rounded">npm run dev:all</code> uses concurrently to start backend + frontend together</li>
            <li>Or run in two terminals: backend <code className="bg-zinc-800 px-1 rounded">python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload</code> and frontend <code className="bg-zinc-800 px-1 rounded">npm run dev:frontend</code></li>
            <li>Added CORS middleware in FastAPI and allowedDevOrigins for <code className="bg-zinc-800 px-1 rounded">*.e2b.app</code></li>
          </ul>
        </section>
      </div>
    </main>
  );
}

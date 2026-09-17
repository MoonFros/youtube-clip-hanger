"use client";
import { useEffect, useState } from "react";

type Job = {
  id: string;
  jobId?: string;
  job_id?: string;
  url: string;
  start_time: string;
  end_time: string;
  status: "queued" | "processing" | "completed" | "failed";
  created_at: string;
  clip_path?: string;
  title?: string;
  error?: string;
};

export default function Home() {
  const [health, setHealth] = useState<any>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [url, setUrl] = useState("");
  const [start, setStart] = useState("00:00:00");
  const [end, setEnd] = useState("00:00:10");
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<"youtube" | "upload">("youtube");
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
      let res: Response;
      
      if (mode === "upload" && file) {
        // File upload via FormData
        const form = new FormData();
        form.append("file", file);
        form.append("start_time", start);
        form.append("end_time", end);
        // Also append url for compatibility if needed
        if (url) form.append("url", url);
        
        res = await fetch("/api/jobs", {
          method: "POST",
          body: form,
        });
      } else {
        // YouTube URL via JSON - FIX for 422 error
        if (!url) throw new Error("YouTube URL is required");
        res = await fetch("/api/jobs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            url, // NOT {source: {type: upload}} - that was the bug
            start_time: start,
            end_time: end,
          }),
        });
      }
      
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `Failed: ${res.status}`);
      }
      const job = await res.json();
      // Handle compatibility: backend returns id, jobId, job_id - use whichever exists
      const jobId = job.id || job.jobId || job.job_id;
      if (!jobId || jobId === "undefined") {
        throw new Error(`Backend returned invalid id: ${jobId}. Response: ${JSON.stringify(job)}`);
      }
      setJobs((prev) => [job, ...prev]);
      setUrl("");
      setFile(null);
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
            <p className="text-zinc-400 mt-1">YouTube + Upload clipping - fixed 422 & undefined bugs</p>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <span className={`w-2 h-2 rounded-full ${health ? "bg-green-500" : "bg-red-500"} animate-pulse`} />
            <span className="text-zinc-400">
              {health ? `API OK (${health.status})` : "API disconnected"}
            </span>
            <button onClick={fetchHealth} className="ml-2 px-3 py-1 bg-zinc-800 rounded hover:bg-zinc-700">Retry</button>
          </div>
        </header>

        {health && (
          <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-3 text-xs font-mono text-zinc-400">
            <div>yt-dlp: {health.yt_dlp_available ? "✅" : "❌ (pip install yt-dlp)"} | ffmpeg: {health.ffmpeg_available ? "✅" : "❌ (install ffmpeg for real clipping, currently mock mode)"}</div>
            { !health.ffmpeg_available && <div className="text-yellow-400 mt-1">⚠️ ffmpeg not found - YouTube clips will be mocked as completed, not actually downloaded. Install ffmpeg for real clipping. Uploads will still work.</div>}
          </div>
        )}

        {error && (
          <div className="bg-red-950 border border-red-800 text-red-200 p-4 rounded">
            <p className="font-mono text-sm">{error}</p>
            <p className="text-xs mt-2 text-red-300">
              Fixes: 
              - 422 error = you sent {`{source: {type: upload}}`} without file/url. Now fixed to send {`{url: ...}`}.
              - /api/jobs/undefined 404 = frontend used data.jobId but backend returned data.id. Now backend returns both id and jobId.
              - YouTube not fetching = need ffmpeg installed. On Windows: choco install ffmpeg or download from ffmpeg.org
              - Upload not working = need to use FormData with file, not JSON with source.type
            </p>
          </div>
        )}

        <section className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
          <h2 className="text-lg font-semibold mb-4">Create Clip</h2>
          <div className="flex gap-2 mb-4">
            <button 
              onClick={() => setMode("youtube")}
              className={`px-4 py-2 rounded-lg text-sm ${mode === "youtube" ? "bg-white text-black" : "bg-zinc-800 text-zinc-400"}`}
            >YouTube URL</button>
            <button 
              onClick={() => setMode("upload")}
              className={`px-4 py-2 rounded-lg text-sm ${mode === "upload" ? "bg-white text-black" : "bg-zinc-800 text-zinc-400"}`}
            >Upload Video</button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {mode === "youtube" ? (
              <div>
                <label className="text-sm text-zinc-400">YouTube URL (required)</label>
                <input
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://www.youtube.com/watch?v=..."
                  className="w-full mt-1 px-4 py-2.5 bg-zinc-950 border border-zinc-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-white/20"
                  required={mode === "youtube"}
                />
              </div>
            ) : (
              <div>
                <label className="text-sm text-zinc-400">Upload Video File (mp4, webm, etc)</label>
                <input
                  type="file"
                  accept="video/*"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  className="w-full mt-1 px-4 py-2.5 bg-zinc-950 border border-zinc-800 rounded-lg"
                  required={mode === "upload"}
                />
                {file && <p className="text-xs text-zinc-500 mt-1">Selected: {file.name} ({(file.size/1024/1024).toFixed(2)} MB)</p>}
              </div>
            )}
            
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
              {loading ? "Creating..." : mode === "youtube" ? "Create YouTube Clip" : "Upload & Clip"}
            </button>
          </form>
        </section>

        <section className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Jobs ({jobs.length})</h2>
            <button onClick={fetchJobs} className="text-sm px-3 py-1 bg-zinc-800 rounded hover:bg-zinc-700">Refresh</button>
          </div>
          {jobs.length === 0 ? (
            <p className="text-zinc-500 text-sm">No jobs yet. Create one above.</p>
          ) : (
            <div className="space-y-3">
              {jobs.map((job) => {
                const displayId = job.id || job.jobId || job.job_id || "unknown";
                return (
                  <div key={displayId} className="flex justify-between items-center p-4 bg-zinc-950 border border-zinc-800 rounded-lg">
                    <div className="min-w-0">
                      <p className="font-medium truncate">{job.title || job.url}</p>
                      <p className="text-xs text-zinc-500 font-mono truncate">{job.url} | {job.start_time} → {job.end_time}</p>
                      <p className="text-xs text-zinc-600 mt-1">{new Date(job.created_at).toLocaleString()} | ID: {displayId}</p>
                      {job.error && <p className="text-xs text-yellow-500 mt-1">{job.error}</p>}
                    </div>
                    <div className="ml-4 flex flex-col items-end gap-1">
                      <span className={`text-xs px-2 py-1 rounded-full ${
                        job.status === "completed" ? "bg-green-950 text-green-300 border border-green-800" :
                        job.status === "failed" ? "bg-red-950 text-red-300 border border-red-800" :
                        job.status === "processing" ? "bg-yellow-950 text-yellow-300 border border-yellow-800" :
                        "bg-zinc-800 text-zinc-400"
                      }`}>{job.status}</span>
                      {job.clip_path && <a href={job.clip_path} target="_blank" className="text-xs text-white underline">Download / View</a>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
          <h3 className="font-semibold mb-2">Fixed bugs in this update</h3>
          <ul className="list-disc list-inside text-sm text-zinc-400 space-y-1">
            <li><b>422 Field required url</b>: Frontend was sending {`{source: {type: upload}}`} → fixed to {`{url: ...}`}</li>
            <li><b>GET /api/jobs/undefined 404</b>: Frontend did `data.jobId` but backend returned `data.id` → now backend returns both id, jobId, job_id</li>
            <li><b>YouTube not fetching</b>: Need ffmpeg. Without it, backend mocks as completed. Install ffmpeg: Windows `choco install ffmpeg` or https://ffmpeg.org</li>
            <li><b>Upload not working</b>: Must use FormData with file, not JSON. New UI has Upload tab that does this correctly</li>
            <li>Backend now handles uploaded files: saves to clips/ and serves via /clips/...</li>
          </ul>
        </section>
      </div>
    </main>
  );
}

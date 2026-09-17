// ---- types ----
export type JobPublic = {
  id: string;
  source_type: string;
  source: string;
  status: string;
  stage: string;
  progress: number;
  detail?: string;
  error: string;
  name: string;
  duration: number;
  width: number;
  height: number;
  fps: number;
  has_audio: boolean;
  letterbox: { top: number; bottom: number };
  scenes: number[];
  suggested_clips: SugClip[];
  created: number;
  demo: boolean;
};

export type SugClip = {
  id: string;
  start: number;
  end: number;
  score: number;
  label: string;
};

export type Word = { w: string; t0: number; t1: number };

export type Analysis = {
  job: JobPublic;
  waveform: { rms?: number[]; low?: number[]; mid?: number[]; high?: number[]; dt: number };
  stems: { status: string; env?: { dialogue: number[]; music: number[]; sfx: number[]; rms: number[] } };
  transcript: {
    status: string;
    reason?: string;
    text?: string;
    words?: Word[];
    engine?: string;
  };
  templates: TemplateMeta[];
};

export type TemplateMeta = {
  id: string;
  name: string;
  emoji: string;
  tagline: string;
  desc: string;
  elements: string[];
  bookend?: boolean;
};

export type ClipPublic = {
  id: string;
  job_id: string;
  start: number;
  end: number;
  duration: number;
  name: string;
  template: string;
  bookend: {
    enabled: boolean;
    style: string;
    intro_text: string;
    outro_text: string;
    fact: string;
    voice: string;
    tts_status: string;
    script_engine?: string;
  };
  audio: Record<string, { mode: string; gain: number }>;
  renders: string[];
};

export type RenderPublic = {
  id: string;
  clip_id: string;
  job_id: string;
  template: string;
  options: any;
  status: string;
  stage: string;
  progress: number;
  detail?: string;
  error: string;
  duration: number;
  size: number;
  preflight: Preflight;
  created: number;
};

export type Preflight = {
  score?: number;
  verdict?: string;
  avg_similarity?: number;
  similarity_timeline?: number[];
  warnings?: { id: string; type: string; msg: string; fix: { action: string; label: string } }[];
  rules?: Record<string, any>;
};

export type Health = {
  ok: boolean;
  yt_dlp?: string;
  ffmpeg?: string;
  plan: string;
  demo_ready: boolean;
  demo_generating: boolean;
  demo_error: string;
  tts_voices: Record<string, { label: string; desc: string }>;
  hook_styles: Record<string, string>;
  tiers: any;
  pro_price: string;
  legal_disclaimer: string;
};

// Base URL of the FairClip API.
// - Local dev / docker compose: "" (same origin, Next rewrites proxy to :8000)
// - Vercel + Render: set NEXT_PUBLIC_API_BASE=https://your-api.onrender.com
export const API_BASE: string = process.env.NEXT_PUBLIC_API_BASE || "";

/** Absolute URL for any backend route (api or media). */
export function url(path: string): string {
  return API_BASE + path;
}

export async function api<T = any>(path: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(url(path), {
    ...opts,
    headers: { "Content-Type": "application/json", ...(opts?.headers || {}) },
  });
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = j.detail || JSON.stringify(j);
    } catch {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

/** Cancel a running ingest/analysis job (cooperative). */
export async function cancelJob(jobId: string): Promise<void> {
  await api(`/api/jobs/${jobId}`, { method: "DELETE" });
}

export function fmtTime(s: number): string {
  if (!isFinite(s)) return "0:00";
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  return `${m}:${sec < 10 ? "0" : ""}${sec.toFixed(sec < 10 ? 1 : 0)}`;
}

export const STAGE_LABELS: Record<string, string> = {
  demo: "Building the demo video (first run only)",
  downloading: "Downloading the source video",
  probing: "Reading video",
  preview: "Preparing preview",
  scenes: "Detecting scenes",
  "audio-profile": "Analyzing audio",
  stems: "Separating audio layers (AI)",
  transcript: "Transcribing (AI)",
};

export const ELEMENT_LABELS: Record<string, string> = {
  captions: "Dynamic captions",
  reframe: "9:16 reframe",
  zoom: "Zoom transform",
  microcut: "Micro-cuts ≤7s",
  audio_duck: "Music ducking",
  layout: "Layout change",
  graphics: "Graphical elements",
  grade: "Color grade",
  grain: "Film grain",
  speed: "Speed ramp",
  blur: "Blur framing",
  tts: "AI bookend voice",
};

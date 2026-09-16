"use client";

import { useApp } from "../AppProvider";
import { ClipPublic, JobPublic, TemplateMeta, ELEMENT_LABELS } from "../../lib/api";

export default function TemplatesTab({
  job,
  clip,
  templates,
  onPatch,
}: {
  job: JobPublic;
  clip: ClipPublic;
  templates: TemplateMeta[];
  onPatch: (p: any) => void;
}) {
  const { toast } = useApp();

  const autoFairUse = () => {
    const template = clip.bookend.enabled ? "breakdown_bookend" : "caption_storm";
    onPatch({
      template,
      audio: {
        ...clip.audio,
        music: { mode: "duck", gain: 1 },
      },
    });
    toast(
      `Auto-Fair Use applied: reframe + micro-cuts ≤7s + captions + music ducked to ~18%`,
      "success"
    );
  };

  return (
    <div>
      <button
        onClick={autoFairUse}
        className="mb-4 w-full rounded-xl bg-gradient-to-r from-accent to-accent-dim px-4 py-3 text-sm font-bold text-white shadow-glow transition hover:brightness-110"
      >
        ⚡ Auto-Fair Use — apply the full transformation stack
      </button>

      <div className="grid gap-2 sm:grid-cols-2">
        {templates.map((t) => {
          const active = clip.template === t.id;
          return (
            <button
              key={t.id}
              onClick={() => {
                onPatch({ template: t.id });
                toast(`${t.name} selected — preview updated`, "info");
              }}
              className={`rounded-xl border p-3 text-left transition ${
                active
                  ? "border-accent bg-accent/10"
                  : "border-ink-600 bg-ink-850 hover:border-accent/50"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-xl">{t.emoji}</span>
                {active && <span className="rounded-full bg-accent px-2 py-0.5 text-[10px] font-bold text-white">ACTIVE</span>}
              </div>
              <p className="mt-1.5 text-sm font-semibold text-white">{t.name}</p>
              <p className="mt-0.5 text-[11px] leading-snug text-zinc-400">{t.tagline}</p>
              <div className="mt-2 flex flex-wrap gap-1">
                {t.elements.slice(0, 4).map((e) => (
                  <span key={e} className="rounded-full bg-ink-700 px-2 py-0.5 text-[9px] text-zinc-300">
                    {ELEMENT_LABELS[e] || e}
                  </span>
                ))}
              </div>
            </button>
          );
        })}
      </div>

      <p className="mt-4 text-[11px] leading-relaxed text-zinc-500">
        Every template already includes the core Fair Use stack: 16:9 → 9:16 reframe with letterbox
        removal, micro-cuts every ≤7s, dynamic word captions, and music ducking to 15–20%.
      </p>
    </div>
  );
}

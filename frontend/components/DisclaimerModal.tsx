"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { useApp } from "./AppProvider";

export default function DisclaimerModal() {
  const { health, disclaimerSeen, setDisclaimerSeen } = useApp();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (health && !disclaimerSeen) {
      const t = setTimeout(() => setOpen(true), 400);
      return () => clearTimeout(t);
    }
  }, [health, disclaimerSeen]);

  if (!open || !health) return null;
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="fixed inset-0 z-[90] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onClick={() => setOpen(false)}
    >
      <motion.div
        initial={{ scale: 0.92, y: 20 }}
        animate={{ scale: 1, y: 0 }}
        onClick={(e) => e.stopPropagation()}
        className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-ink-600 bg-ink-900 p-6 shadow-glow"
      >
        <div className="mb-3 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/20 text-xl">⚖️</div>
          <div>
            <h2 className="text-lg font-semibold text-white">Before you create clips</h2>
            <p className="text-xs text-zinc-400">Please read — this matters for everyone's content</p>
          </div>
        </div>
        <p className="mb-4 whitespace-pre-line text-sm leading-relaxed text-zinc-300">
          {health.legal_disclaimer || "FairClip is a creative tool, not legal advice."}
        </p>
        <button
          onClick={() => {
            setDisclaimerSeen();
            setOpen(false);
          }}
          className="w-full rounded-xl bg-accent px-4 py-3 text-sm font-semibold text-white transition hover:bg-accent-soft"
        >
          I understand — start clipping
        </button>
        <p className="mt-3 text-center text-[11px] text-zinc-500">
          You can re-read this anytime from the Export panel.
        </p>
      </motion.div>
    </motion.div>
  );
}

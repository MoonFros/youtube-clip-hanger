"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { url } from "../lib/api";

type Toast = { id: number; kind: "info" | "success" | "error"; msg: string };
type Ctx = {
  toast: (msg: string, kind?: Toast["kind"]) => void;
  health: any;
  backendWarning: string;
  disclaimerSeen: boolean;
  setDisclaimerSeen: () => void;
};

const ToastCtx = createContext<Ctx>(null as any);
export const useApp = () => useContext(ToastCtx);

let tid = 1;

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [health, setHealth] = useState<any>(null);
  const [backendWarning, setBackendWarning] = useState("");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [disclaimerSeen, setDisclaimerSeen] = useState(
    typeof window !== "undefined" && !!localStorage.getItem("fairclip-disclaimer")
  );

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(url("/api/health"));
        const h = await res.json();
        if (!h || h.ok !== true) {
          // The legacy single-file backend ("massreels_backend.py") answers on
          // /api/health too, but with a completely different API — every action
          // would fail with 404/422 and jobs that never finish. Say so loudly.
          setBackendWarning(
            "Something else is answering on the API port. You are most likely running the old " +
              "legacy backend (uvicorn backend.main:app / run.bat from an older checkout) instead of " +
              "FairClip. Stop it and start the app with ./run.sh (or run.bat) — see README → Troubleshooting."
          );
        } else {
          setBackendWarning("");
        }
        setHealth(h);
      } catch (e) {
        console.error("health", e);
        setBackendWarning(
          "Cannot reach the FairClip backend. Start it with ./run.sh (or run.bat) and reload — " +
            "the API must be listening on port 8000."
        );
      }
    })();
  }, []);

  const toast = useCallback((msg: string, kind: Toast["kind"] = "info") => {
    const id = tid++;
    setToasts((t) => [...t, { id, kind, msg }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);

  const setDisclaimerSeenFn = useCallback(() => {
    try {
      localStorage.setItem("fairclip-disclaimer", "1");
    } catch {}
    setDisclaimerSeen(true);
  }, []);

  return (
    <ToastCtx.Provider value={{ toast, health, backendWarning, disclaimerSeen, setDisclaimerSeen: setDisclaimerSeenFn }}>
      {backendWarning ? (
        <div className="border-b border-red-900/60 bg-red-950/70 px-4 py-2 text-center text-xs text-red-200">
          ⚠️ {backendWarning}
        </div>
      ) : null}
      {children}
      <div className="pointer-events-none fixed right-4 top-4 z-[100] flex w-[320px] flex-col gap-2">
        <AnimatePresence>
          {toasts.map((t) => (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, x: 40 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 40 }}
              className={`pointer-events-auto rounded-xl border px-4 py-3 text-sm shadow-lg backdrop-blur ${
                t.kind === "error"
                  ? "border-red-800/60 bg-red-950/80 text-red-200"
                  : t.kind === "success"
                    ? "border-emerald-800/60 bg-emerald-950/80 text-emerald-200"
                    : "border-ink-600 bg-ink-800/90 text-zinc-200"
              }`}
            >
              {t.msg}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  );
}

"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

type Toast = { id: number; kind: "info" | "success" | "error"; msg: string };
type Ctx = {
  toast: (msg: string, kind?: Toast["kind"]) => void;
  health: any;
  disclaimerSeen: boolean;
  setDisclaimerSeen: () => void;
};

const ToastCtx = createContext<Ctx>(null as any);
export const useApp = () => useContext(ToastCtx);

let tid = 1;

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [health, setHealth] = useState<any>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [disclaimerSeen, setDisclaimerSeen] = useState(
    typeof window !== "undefined" && !!localStorage.getItem("fairclip-disclaimer")
  );

  useEffect(() => {
    (async () => {
      try {
        const h = await fetch("/api/health").then((r) => r.json());
        setHealth(h);
      } catch (e) {
        console.error("health", e);
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
    <ToastCtx.Provider value={{ toast, health, disclaimerSeen, setDisclaimerSeen: setDisclaimerSeenFn }}>
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

"use client";

import { useEffect, useState } from "react";

import { queueSummaryLabel } from "@/lib/queue-focus";
import type { OverseerSnapshot } from "@/lib/types";

const statusColors: Record<string, string> = {
  IDLE: "bg-slate-700 text-slate-200",
  PENDING: "bg-slate-600 text-slate-100",
  RUNNING: "bg-sky-700 text-sky-100",
  NEEDS_REPAIR: "bg-amber-700 text-amber-100",
  COMPLETED: "bg-emerald-800 text-emerald-100",
  ABORTED: "bg-rose-800 text-rose-100",
};

export function Header() {
  const [snapshot, setSnapshot] = useState<OverseerSnapshot | null>(null);

  useEffect(() => {
    const load = async () => {
      const res = await fetch("/api/state");
      if (res.ok) setSnapshot(await res.json());
    };
    void load();
    const timer = setInterval(load, 1500);
    return () => clearInterval(timer);
  }, []);

  const status = snapshot?.aggregate_status ?? "IDLE";

  return (
    <header className="panel flex flex-wrap items-center justify-between gap-4 p-5">
      <div>
        <p className="text-xs uppercase tracking-[0.2em] text-slate-400">
          Sleeper Agent
        </p>
        <h1 className="text-2xl font-semibold text-white">AFK Overseer</h1>
        <p className="mt-1 text-sm text-slate-400">
          Give one initiate command, then step away. The overseer manages retries
          while you are offline.
        </p>
      </div>
      <div className="flex flex-col items-end gap-2 text-sm">
        <span className={`status-pill ${statusColors[status] ?? statusColors.IDLE}`}>
          {status}
        </span>
        <span className="text-slate-400">
          Backend: <span className="text-accent">{snapshot?.backend ?? "—"}</span>
        </span>
        {snapshot?.active_queue_id ? (
          <span className="text-xs text-slate-500">
            {snapshot.queues.find((q) => q.id === snapshot.active_queue_id)
              ? queueSummaryLabel(
                  snapshot.queues.find((q) => q.id === snapshot.active_queue_id)!,
                )
              : "latest session"}
          </span>
        ) : null}
      </div>
    </header>
  );
}

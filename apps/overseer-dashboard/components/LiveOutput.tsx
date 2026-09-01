"use client";

import { useEffect, useMemo, useState } from "react";

import type { OverseerSnapshot, QueueRecord } from "@/lib/types";

function activeQueue(snapshot: OverseerSnapshot | null): QueueRecord | null {
  if (!snapshot?.active_queue_id) return snapshot?.queues[0] ?? null;
  return (
    snapshot.queues.find((q) => q.id === snapshot.active_queue_id) ??
    snapshot.queues[0] ??
    null
  );
}

export function LiveOutput() {
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

  const queue = useMemo(() => activeQueue(snapshot), [snapshot]);
  const latest = queue?.history[queue.history.length - 1];

  const lines = queue
    ? [
        queue.status === "COMPLETED" ? "Session completed successfully." : null,
        latest?.stdout,
        queue.status === "NEEDS_REPAIR" ? latest?.stderr : null,
        queue.status === "NEEDS_REPAIR"
          ? (queue.last_error as { traceback?: string } | null)?.traceback
          : null,
      ]
        .filter(Boolean)
        .join("\n\n")
    : "";

  return (
    <section className="panel flex min-h-[320px] flex-col p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-300">
        Live Output
      </h2>
      <p className="mt-1 text-sm text-slate-500">
        Terminal stream from the latest sandbox or browser task.
      </p>
      <pre className="mt-4 flex-1 overflow-auto rounded-lg border border-surface-border bg-black/40 p-4 font-mono text-xs leading-relaxed text-slate-300">
        {lines || "Waiting for overseer output…"}
      </pre>
    </section>
  );
}

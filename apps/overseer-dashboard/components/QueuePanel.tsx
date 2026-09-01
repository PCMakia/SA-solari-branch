"use client";

import { useEffect, useMemo, useState } from "react";

import { queueSummaryLabel } from "@/lib/queue-focus";
import type { OverseerSnapshot, QueueRecord } from "@/lib/types";

function activeQueue(snapshot: OverseerSnapshot | null): QueueRecord | null {
  if (!snapshot?.active_queue_id) return null;
  return (
    snapshot.queues.find((q) => q.id === snapshot.active_queue_id) ?? null
  );
}

export function QueuePanel() {
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
  const progress =
    queue && queue.tasks.length > 0
      ? Math.round((queue.current_step_index / queue.tasks.length) * 100)
      : 0;

  return (
    <section className="panel p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-300">
          Queue
        </h2>
        <span className="text-xs text-slate-500">
          {snapshot?.completed_steps ?? 0}/{snapshot?.total_steps ?? 0} steps
        </span>
      </div>

      {!queue ? (
        <p className="mt-4 text-sm text-slate-500">
          No active overseer session. Start one from Cursor.
        </p>
      ) : (
        <>
          <p className="mt-2 text-sm text-white">
            Session: <span className="text-accent">{queueSummaryLabel(queue)}</span>
          </p>
          <p className="text-xs text-slate-500">
            Status {queue.status}
            {snapshot && snapshot.queues.length > 1
              ? ` · showing latest of ${snapshot.queues.length} in state file`
              : ""}
          </p>
          <div className="mt-4 h-2 overflow-hidden rounded-full bg-black/40">
            <div
              className="h-full rounded-full bg-accent transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
          <p className="mt-2 truncate font-mono text-xs text-slate-500">
            {queue.id}
          </p>
          <ul className="mt-4 space-y-2">
            {queue.tasks.map((task, index) => {
              const isActive = index === queue.current_step_index;
              const isDone = index < queue.current_step_index;
              return (
                <li
                  key={task.id}
                  className={`rounded-lg border px-3 py-2 text-sm ${
                    isActive
                      ? "border-accent/40 bg-accent/10"
                      : "border-surface-border bg-black/20"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-white">{task.id}</span>
                    <span className="text-xs uppercase text-slate-500">
                      {task.runtime ?? "sandbox"}
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-xs text-slate-400">
                    {task.command} {task.args.join(" ")}
                  </p>
                  {task.url ? (
                    <p className="mt-1 truncate text-xs text-slate-500">{task.url}</p>
                  ) : null}
                  <p className="mt-1 text-xs text-slate-500">
                    {isDone ? "done" : isActive ? "running" : "pending"}
                    {" · "}
                    retries {queue.retry_counts[task.id] ?? 0}
                  </p>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}

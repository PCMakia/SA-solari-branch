import { promises as fs } from "fs";
import os from "os";
import path from "path";

import { aggregateStatus, pickActiveQueue } from "./queue-focus";
import type { OverseerSnapshot, QueueRecord, QueueStatus } from "./types";

function defaultStatePath(): string {
  return path.join(os.homedir(), ".sleeper_agent", "queue_state.json");
}

export function resolveStatePath(): string {
  return process.env.SLEEPER_STATE_PATH?.trim() || defaultStatePath();
}

export async function readOverseerSnapshot(): Promise<OverseerSnapshot> {
  const statePath = resolveStatePath();
  let queues: QueueRecord[] = [];

  try {
    const raw = await fs.readFile(statePath, "utf8");
    const parsed = JSON.parse(raw) as { queues?: Record<string, QueueRecord> };
    queues = Object.values(parsed.queues ?? {});
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      throw error;
    }
  }

  const active = pickActiveQueue(queues);
  const completedSteps = active
    ? active.history.filter((h) => h.status === "success").length
    : 0;
  const totalSteps = active?.tasks.length ?? 0;

  return {
    state_path: statePath,
    backend: process.env.SLEEPER_BACKEND?.trim() || "solari",
    aggregate_status: aggregateStatus(queues),
    active_queue_id: active?.id ?? null,
    queues,
    completed_steps: completedSteps,
    total_steps: totalSteps,
    timestamp: new Date().toISOString(),
  };
}

/** Remove non-running queues from the shared state file. */
export async function resetOverseerState(
  mode: "stale" | "all" = "stale",
): Promise<{ removed: number; kept: number }> {
  const statePath = resolveStatePath();
  let queues: Record<string, QueueRecord> = {};

  try {
    const raw = await fs.readFile(statePath, "utf8");
    const parsed = JSON.parse(raw) as { queues?: Record<string, QueueRecord> };
    queues = parsed.queues ?? {};
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      throw error;
    }
  }

  const next: Record<string, QueueRecord> = {};
  if (mode === "stale") {
    for (const [id, record] of Object.entries(queues)) {
      if (record.status === "RUNNING") {
        next[id] = record;
      }
    }
  }

  await fs.mkdir(path.dirname(statePath), { recursive: true });
  await fs.writeFile(
    statePath,
    JSON.stringify({ queues: next }, null, 2),
    "utf8",
  );

  return {
    removed: Object.keys(queues).length - Object.keys(next).length,
    kept: Object.keys(next).length,
  };
}

export type { QueueStatus };

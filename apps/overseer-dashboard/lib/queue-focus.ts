import type { QueueRecord, QueueStatus } from "./types";

export function queueLastActivity(queue: QueueRecord): number {
  const last = queue.history[queue.history.length - 1];
  if (last?.timestamp) {
    const ms = Date.parse(last.timestamp);
    if (!Number.isNaN(ms)) return ms;
  }
  return 0;
}

export function sortQueuesByRecency(queues: QueueRecord[]): QueueRecord[] {
  return [...queues].sort((a, b) => queueLastActivity(b) - queueLastActivity(a));
}

/** Prefer an explicit deep-linked queue id when present in state. */
export function resolveFocusedQueue(
  queues: QueueRecord[],
  preferredQueueId: string | null | undefined,
): QueueRecord | null {
  if (preferredQueueId) {
    const match = queues.find((q) => q.id === preferredQueueId);
    if (match) return match;
  }
  return pickActiveQueue(queues);
}

/** Focus the queue the user most likely cares about right now. */
export function pickActiveQueue(queues: QueueRecord[]): QueueRecord | null {
  if (queues.length === 0) return null;

  const recent = sortQueuesByRecency(queues);
  const running = recent.find((q) => q.status === "RUNNING");
  if (running) return running;

  const pending = recent.find((q) => q.status === "PENDING");
  if (pending) return pending;

  // Prefer the most recently touched queue (completed, needs repair, etc.)
  return recent[0] ?? null;
}

export function aggregateStatus(
  queues: QueueRecord[],
): QueueStatus | "IDLE" {
  if (queues.length === 0) return "IDLE";
  if (queues.some((q) => q.status === "RUNNING")) return "RUNNING";

  const active = pickActiveQueue(queues);
  return active?.status ?? "IDLE";
}

export function queueSummaryLabel(queue: QueueRecord): string {
  if (queue.label) return queue.label;
  if (queue.tasks.length === 0) return queue.id.slice(0, 8);
  return queue.tasks.map((t) => t.id).join(" + ");
}

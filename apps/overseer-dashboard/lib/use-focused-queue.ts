"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import { resolveFocusedQueue } from "@/lib/queue-focus";
import type { OverseerSnapshot, QueueRecord } from "@/lib/types";

export function useFocusedQueue(): {
  snapshot: OverseerSnapshot | null;
  queue: QueueRecord | null;
  preferredQueueId: string | null;
} {
  const searchParams = useSearchParams();
  const preferredQueueId = searchParams.get("queue_id");
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

  const queue = useMemo(() => {
    if (!snapshot) return null;
    return resolveFocusedQueue(snapshot.queues, preferredQueueId);
  }, [snapshot, preferredQueueId]);

  return { snapshot, queue, preferredQueueId };
}

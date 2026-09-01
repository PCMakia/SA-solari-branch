"use client";

import { useState } from "react";

export function ControlPanel() {
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reloadMcp = async (mode: "reload" | "restart") => {
    setBusy(true);
    setMessage(null);
    try {
      const res = await fetch("/api/mcp/reload", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error ?? data.message ?? "MCP reload failed");
      }
      const keyStatus = data.cursor_api_key_set
        ? "CURSOR_API_KEY set"
        : "CURSOR_API_KEY missing";
      setMessage(
        `${data.message} (${keyStatus}; ${data.applied_keys?.length ?? 0} env keys from global mcp.json)`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "MCP reload failed");
    } finally {
      setBusy(false);
    }
  };

  const resetState = async (mode: "stale" | "all") => {
    setBusy(true);
    setMessage(null);
    try {
      const res = await fetch("/api/state/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error ?? "Reset failed");
      }
      setMessage(
        mode === "all"
          ? `Cleared all ${data.removed} session(s). Dashboard should show IDLE.`
          : `Removed ${data.removed} stale session(s). Kept ${data.kept} running.`,
      );
      setTimeout(() => window.location.reload(), 600);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Reset failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-300">
        Initiate
      </h2>
      <p className="mt-2 text-sm text-slate-400">
        Start sessions from Cursor via{" "}
        <code className="rounded bg-black/30 px-1.5 py-0.5 font-mono text-accent">
          start_afk_overseer
        </code>
        . This dashboard reads{" "}
        <code className="font-mono text-xs">~/.sleeper_agent/queue_state.json</code>.
        Use <strong className="text-slate-300">Reset all</strong> if old failed
        sessions keep appearing — new runs now auto-prune stale queues.
        Use <strong className="text-slate-300">Reload MCP env</strong> after
        editing <code className="font-mono text-xs">~/.cursor/mcp.json</code>,
        or <strong className="text-slate-300">Restart MCP server</strong> to
        force Cursor to respawn the process.
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => void reloadMcp("reload")}
          className="rounded-lg border border-accent/40 bg-accent/10 px-3 py-2 text-sm text-accent hover:bg-accent/20 disabled:opacity-50"
        >
          Reload MCP env
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void reloadMcp("restart")}
          className="rounded-lg border border-sky-900/60 bg-sky-950/30 px-3 py-2 text-sm text-sky-200 hover:border-sky-700 disabled:opacity-50"
        >
          Restart MCP server
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void resetState("stale")}
          className="rounded-lg border border-surface-border bg-black/30 px-3 py-2 text-sm text-slate-200 hover:border-accent/40 disabled:opacity-50"
        >
          Clear stale sessions
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void resetState("all")}
          className="rounded-lg border border-rose-900/60 bg-rose-950/30 px-3 py-2 text-sm text-rose-200 hover:border-rose-700 disabled:opacity-50"
        >
          Reset all
        </button>
      </div>
      {message ? <p className="mt-3 text-sm text-slate-400">{message}</p> : null}

      <div className="mt-4 space-y-3 rounded-lg border border-surface-border bg-black/20 p-4 text-sm text-slate-300">
        <p className="font-medium text-white">Example task queue</p>
        <pre className="overflow-x-auto font-mono text-xs leading-relaxed text-slate-400">
{`[
  { "id": "hello", "command": "python",
    "args": ["-c", "print(42)"] }
]`}
        </pre>
      </div>
    </section>
  );
}

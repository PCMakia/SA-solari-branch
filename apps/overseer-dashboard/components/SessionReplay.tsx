"use client";

export function SessionReplay() {
  return (
    <section className="panel p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-300">
        Session Replay
      </h2>
      <p className="mt-1 text-sm text-slate-500">
        Browser tasks recorded with Solari will surface replay URLs here in a
        later iteration. The scaffold reserves this panel for rrweb playback.
      </p>
      <div className="mt-4 flex aspect-video items-center justify-center rounded-lg border border-dashed border-surface-border bg-black/30 text-sm text-slate-500">
        Replay player placeholder
      </div>
    </section>
  );
}

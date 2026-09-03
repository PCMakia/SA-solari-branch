"use client";

import { Suspense } from "react";

import { ControlPanel } from "@/components/ControlPanel";
import { Header } from "@/components/Header";
import { LiveOutput } from "@/components/LiveOutput";
import { QueuePanel } from "@/components/QueuePanel";
import { SessionReplay } from "@/components/SessionReplay";

function DashboardBody() {
  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6 px-6 py-8">
      <Header />
      <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
        <div className="flex flex-col gap-6">
          <ControlPanel />
          <QueuePanel />
        </div>
        <div className="flex flex-col gap-6">
          <LiveOutput />
          <SessionReplay />
        </div>
      </div>
    </div>
  );
}

export default function HomePage() {
  return (
    <main className="min-h-screen">
      <Suspense fallback={<div className="p-8 text-slate-400">Loading overseer…</div>}>
        <DashboardBody />
      </Suspense>
    </main>
  );
}

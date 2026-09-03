import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/** Lightweight liveness probe for sleeper_daemon (no queue/state I/O). */
export async function GET() {
  return NextResponse.json({ status: "ok" });
}

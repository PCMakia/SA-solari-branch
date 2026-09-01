import { NextResponse } from "next/server";

import { resetOverseerState } from "@/lib/state";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => ({}))) as { mode?: string };
    const mode = body.mode === "all" ? "all" : "stale";
    const result = await resetOverseerState(mode);
    return NextResponse.json({ status: "OK", mode, ...result });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Reset failed" },
      { status: 500 },
    );
  }
}

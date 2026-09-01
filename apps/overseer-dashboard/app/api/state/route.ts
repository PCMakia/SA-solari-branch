import { NextResponse } from "next/server";

import { readOverseerSnapshot } from "@/lib/state";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const snapshot = await readOverseerSnapshot();
    return NextResponse.json(snapshot);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Failed to read state" },
      { status: 500 },
    );
  }
}

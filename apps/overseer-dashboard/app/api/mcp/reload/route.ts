import { NextResponse } from "next/server";

import { reloadMcpServer } from "@/lib/mcp-reload";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => ({}))) as { mode?: string };
    const mode = body.mode === "reload" ? "reload" : "restart";
    const result = await reloadMcpServer(mode);
    const statusCode = result.status === "ERROR" ? 500 : 200;
    return NextResponse.json(result, { status: statusCode });
  } catch (error) {
    return NextResponse.json(
      {
        status: "ERROR",
        error: error instanceof Error ? error.message : "MCP reload failed",
      },
      { status: 500 },
    );
  }
}

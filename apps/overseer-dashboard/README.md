# Sleeper Overseer Dashboard

Web UI for the **Sleeper AFK Overseer** monorepo. Polls `~/.sleeper_agent/queue_state.json`
and shows queue progress, live terminal output, and a placeholder for Solari browser replays.

## Prerequisites

- Node.js 18+
- MCP server configured — see [../../docs/mcp.json.example](../../docs/mcp.json.example)
- An active session via `start_afk_overseer` from Cursor

## Setup

```bash
cd apps/overseer-dashboard
npm install
cp .env.example .env.local   # optional
npm run dev
```

Open http://localhost:3000

## Environment (`.env.local`)

| Variable | Default | Description |
|----------|---------|-------------|
| `SLEEPER_STATE_PATH` | `~/.sleeper_agent/queue_state.json` | Queue state written by MCP |
| `SLEEPER_BACKEND` | `docker` | Header badge only — set `solari` to match MCP |
| `SOLARI_API_KEY` | — | Reserved for future replay routes (not required today) |

**Solari API key for task execution goes in Cursor `mcp.json`, not here.** See [../../docs/TESTING.md](../../docs/TESTING.md).

## Architecture

```
Cursor MCP (start_afk_overseer)
        │
        ▼
packages/sleeper-mcp ──writes──► ~/.sleeper_agent/queue_state.json
        │                              ▲
        ▼                              │
Solari Sandbox / Browser              │
                                       │
Next.js /api/state ────────────────────┘
```

## Testing

See [../../docs/TESTING.md](../../docs/TESTING.md).

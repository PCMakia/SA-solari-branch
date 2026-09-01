# sleeper-mcp

MCP server for the **Sleeper AFK Overseer** — queue management, Solari sandbox/browser
execution, and self-healing retries. Part of the Solari monorepo.

## Install

From this directory (`packages/sleeper-mcp`):

```bash
pip install -r requirements.txt
```

## Cursor MCP

Copy [../../docs/mcp.json.example](../../docs/mcp.json.example) into `%USERPROFILE%\.cursor\mcp.json`
and set `SOLARI_API_KEY`.

| Setting | Monorepo value |
|---------|----------------|
| `cwd` | `D:/AI_lab/Arifureta/Solari/packages/sleeper-mcp` |
| `SLEEPER_WORKSPACE` | `D:/AI_lab/Arifureta/Solari` |
| `SLEEPER_BACKEND` | `solari` |
| `SOLARI_API_KEY` | Your key from console.getsolari.com |

Restart Cursor after editing `mcp.json`.

## Key tools

- `start_afk_overseer` — enqueue + run in background (AFK entry point)
- `get_queue_status` — poll progress
- `resume_queue` — continue after `NEEDS_REPAIR`

See [../../docs/OVERSEER.md](../../docs/OVERSEER.md) for task schema and architecture.

## Dashboard

[../../apps/overseer-dashboard](../../apps/overseer-dashboard) reads `~/.sleeper_agent/queue_state.json`.

## Manual smoke test

```bash
cd packages/sleeper-mcp
python -c "from sleeper_agent_mcp.backends import run_task; print('imports ok')"
```

Full guide: [../../docs/TESTING.md](../../docs/TESTING.md).

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SLEEPER_BACKEND` | `docker` | `solari` or `docker` |
| `SOLARI_API_KEY` | — | Required when backend is `solari` |
| `SOLARI_BASE_URL` | `https://api.getsolari.com` | Solari API base URL |
| `SLEEPER_WORKSPACE` | cwd | Host files synced into Solari sandbox |
| `SLEEPER_TASK_TIMEOUT` | `600` | Per-task timeout (seconds) |
| `SLEEPER_MAX_CONCURRENT` | computed | Max parallel worker streams |

Docker-only variables (`SLEEPER_DOCKER_IMAGE`, `SLEEPER_TASK_RAM`, etc.) apply when
`SLEEPER_BACKEND=docker`.

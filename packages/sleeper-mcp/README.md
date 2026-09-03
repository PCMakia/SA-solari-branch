# sleeper-mcp

MCP server for the **Sleeper AFK Overseer** — queue management, Solari sandbox/browser
execution, and self-healing retries. Part of the Solari monorepo.

## Install (global Cursor)

From the **repo root**:

```powershell
powershell -ExecutionPolicy Bypass -File packages/sleeper-mcp/install/install_cursor_sleeper.ps1 -SolariApiKey "slr_live_..."
```

Or from this package:

```bash
pip install -e . -r requirements.txt
```

Then merge [install/mcp.json.example](install/mcp.json.example) into
`%USERPROFILE%\.cursor\mcp.json` (set `SLEEPER_HOME` to your clone path and
`SOLARI_API_KEY`), and copy [install/sleeper-afk.mdc](install/sleeper-afk.mdc) to
`%USERPROFILE%\.cursor\rules\`. Restart / reload MCP.

| Setting | Meaning |
|---------|---------|
| `cwd` | `<SLEEPER_HOME>/packages/sleeper-mcp` |
| `SLEEPER_HOME` | Absolute path to this Solari clone (install only) |
| `PYTHONPATH` | sleeper-mcp + sleeper-daemon under `SLEEPER_HOME` |
| `SLEEPER_BACKEND` | `solari` |
| `SOLARI_API_KEY` | Key from console.getsolari.com |

Do **not** set `SLEEPER_WORKSPACE` to the Solari clone for everyday use. Each
`start_afk_overseer` call must pass `workspace=<open project path>`.

## Key tools

- `start_afk_overseer` — enqueue + run in background (AFK entry point; auto-starts daemon watch)
- `get_queue_status` — poll progress
- `resume_queue` — continue after `NEEDS_REPAIR`

### Task schema

| Field | Required | Description |
|-------|----------|-------------|
| `id` | yes | Stable task id |
| `command` | yes | `python`, `pytest`, `npm`, or `node` |
| `args` | no | Argument list |
| `runtime` | no | `sandbox` (default) or `browser` |
| `url` | browser only | Page URL when `runtime` is `browser` |

## Dashboard

[../../apps/overseer-dashboard](../../apps/overseer-dashboard) reads `~/.sleeper_agent/queue_state.json`.

## Manual smoke test

```bash
cd packages/sleeper-mcp
python -c "from sleeper_agent_mcp.backends import get_execution_backend; print('ok')"
python scripts/preflight.py --live
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SLEEPER_HOME` | detected | Solari/Sleeper install root |
| `SLEEPER_BACKEND` | `docker` | `solari` or `docker` |
| `SOLARI_API_KEY` | — | Required when backend is `solari` |
| `SOLARI_BASE_URL` | `https://api.getsolari.com` | Solari API base URL |
| `SLEEPER_TASK_TIMEOUT` | `600` | Per-task timeout (seconds) |
| `SLEEPER_MAX_CONCURRENT` | computed | Max parallel worker streams |

Docker-only variables (`SLEEPER_DOCKER_IMAGE`, `SLEEPER_TASK_RAM`, etc.) apply when
`SLEEPER_BACKEND=docker`.

# Sleeper AFK Overseer

You can now give Cursor one command, and walk away to sleep, gym, do other stuff away from computer.

  
**Sleeper AFK Overseer** is a full-stack agent of [Solari](https://getsolari.com): give one
initiate command from Cursor, step away, and the overseer runs your task queue on Solari
sandboxes and browsers while managing retries and surfacing `NEEDS_REPAIR` when code needs a fix.  

This repo is a monorepo:


| Path                                               | Role                                                             |
| -------------------------------------------------- | ---------------------------------------------------------------- |
| [packages/sleeper-mcp](packages/sleeper-mcp)       | MCP server — queue, Solari/Docker backends, `start_afk_overseer` |
| [packages/sleeper-daemon](packages/sleeper-daemon) | Local watch daemon — pastes kickoff/repair into Cursor chat      |
| [apps/overseer-dashboard](apps/overseer-dashboard) | Next.js UI — live queue, terminal output                         |
| [examples/](examples)                              | Upstream Solari cookbook quickstarts                             |


## How to use with Cursor

Install **this repo once** on your machine. After that, open **any** project in Cursor
(Agent window or IDE) and run task lists with Sleeper — you do **not** copy Sleeper
into each app repo.

### One-time setup

```powershell
git clone <this-repo> C:/tools/Solari
cd C:/tools/Solari
powershell -ExecutionPolicy Bypass -File packages/sleeper-mcp/install/install_cursor_sleeper.ps1 -SolariApiKey "slr_live_..."
```

That wires global `~/.cursor/mcp.json` (`SLEEPER_HOME` = this clone) and installs a
Cursor rule so agents always pass your **open project** as `workspace`. Then reload MCP
(Settings → MCP → toggle `sleeper-agent-mcp`).

Manual alternative: merge [packages/sleeper-mcp/install/mcp.json.example](packages/sleeper-mcp/install/mcp.json.example)
into `%USERPROFILE%\.cursor\mcp.json`, set `SLEEPER_HOME` / `cwd` / `PYTHONPATH` to your clone,
set `SOLARI_API_KEY`, and copy [packages/sleeper-mcp/install/sleeper-afk.mdc](packages/sleeper-mcp/install/sleeper-afk.mdc)
to `%USERPROFILE%\.cursor\rules\`.

### Whenever you have a task list

1. Open the project you want to run against in Cursor.
2. Give the agent a **Sleeper-call** (chat, or write `.sleeper_input` in that project):

```text
"""Sleeper-call
[
  {"id": "step-1", "command": "python", "args": ["path/to/script.py"]},
  {"id": "step-2", "command": "pytest", "args": ["-q"]},
  {"id": "smoke", "runtime": "browser", "command": "python", "args": [], "url": "https://example.com"}
]
"""
```

Or ask in plain language: *Start the AFK overseer with these tasks…* and list the same
`id` / `command` / `args` (optional `runtime` + `url` for browser smoke).

1. The agent should call `start_afk_overseer` with:
  - `workspace` = **this project’s absolute path** (not the Solari clone)
  - your `tasks` array
2. Step away. The overseer runs steps on Solari; on failure it pauses for repair in
  the same Cursor chat (`resume_queue` after fixes). Optional live UI: [http://localhost:3000](http://localhost:3000)

**Task shape:** `id` (required), `command` (`python` | `pytest` | `npm` | `node`),
`args` (list), optional `runtime`: `"sandbox"` (default) or `"browser"` (+ `url`).

**Kill switch:** create `.overseer.stop` in the project root.

## Quick start (developers of this repo)

### 1. Install MCP + daemon

```bash
cd packages/sleeper-mcp && pip install -e . -r requirements.txt
cd ../sleeper-daemon && pip install -e . -r requirements.txt
```

Or run the one-time installer above.

### 2. Solari API key

In `~/.cursor/mcp.json` under `sleeper-agent-mcp.env`, set `SOLARI_API_KEY` from
[console.getsolari.com](https://console.getsolari.com). Use `SLEEPER_HOME` for this clone;
do **not** pin task runs with `SLEEPER_WORKSPACE` to Solari.

### 3. Restart Cursor MCP

Reload so `sleeper-agent-mcp` picks up the config.

### 4. Optional dashboard

```bash
cd apps/overseer-dashboard
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

### 5. Smoke from Cursor

Ask the agent (with this repo or any project open) to call `start_afk_overseer` with
`workspace` set to that project and a small task list, for example:

```json
{
  "tasks": [
    { "id": "hello", "command": "python", "args": ["-c", "print('overseer ok')"] }
  ],
  "workspace": "C:/path/to/your/project",
  "label": "demo"
}
```

Watch progress via `get_queue_status` or the dashboard.

Local preflight (optional):

```bash
python packages/sleeper-mcp/scripts/preflight.py --live
```

---

# Solari Cookbook (origin forked)

Short, runnable examples for [Solari](https://getsolari.com) — cloud browsers,
sandboxes, and desktops behind one API key.

Every example in this repo is a complete program you can run in under a minute.
They are deliberately small: one idea each, no framework, no scaffolding to read
past. Copy one into your project and change the parts you care about.

## Examples

### Cloud browser


| Example                                                               | Language   | What it shows                           |
| --------------------------------------------------------------------- | ---------- | --------------------------------------- |
| [browser-quickstart-ts](examples/browser-quickstart-ts)               | TypeScript | Launch a browser, open a page, read it  |
| [browser-quickstart-py](examples/browser-quickstart-py)               | Python     | Launch a browser, open a page, read it  |
| [browser-stealth-proxy-ts](examples/browser-stealth-proxy-ts)         | TypeScript | Stealth mode + residential proxy egress |
| [browser-profiles-ts](examples/browser-profiles-ts)                   | TypeScript | Log in once, reuse the session forever  |
| [browser-session-recording-py](examples/browser-session-recording-py) | Python     | Record a session, download the replay   |


### Sandbox


| Example                                                             | Language   | What it shows                             |
| ------------------------------------------------------------------- | ---------- | ----------------------------------------- |
| [sandbox-quickstart-ts](examples/sandbox-quickstart-ts)             | TypeScript | Run a command, write and read files       |
| [sandbox-code-interpreter-py](examples/sandbox-code-interpreter-py) | Python     | Stateful Python kernel for agent loops    |
| [sandbox-port-preview-ts](examples/sandbox-port-preview-ts)         | TypeScript | Expose a server in the VM on a public URL |


### Desktop


| Example                                                     | Language | What it shows                              |
| ----------------------------------------------------------- | -------- | ------------------------------------------ |
| [desktop-computer-use-py](examples/desktop-computer-use-py) | Python   | Screenshot, click, and type on a Linux GUI |


## Running an example

Each directory is self-contained.

```bash
cd examples/browser-quickstart-ts

npm install                          # or: pip install -r requirements.txt
export SOLARI_API_KEY=slr_live_...   # grab one at console.getsolari.com
npm start                            # or: python main.py
```

One `slr_live_` key works across browsers, sandboxes, and desktops, and every
product bills to the same balance.

## Which product do I want?

- **Cloud browser** — you need a *web page*: scraping, testing, filling forms,
anything Playwright or Puppeteer would do locally. Adds stealth, managed
proxies, captcha solving, profiles, and session recording.
- **Sandbox** — you need to *run code*: an LLM's Python, an untrusted build, a
data job. A headless microVM that boots from a snapshot in about a second.
- **Desktop** — you need a *screen*: computer-use agents, GUI apps, anything
that has to be clicked. A sandbox plus X11 and a live VNC stream.

## Gotchas the examples encode

Things that cost you an afternoon if you meet them cold:

- **TypeScript: call** `await solari.close()`**.** The browser client keeps a
loopback proxy open for connection retries. Skip the close and your script
prints its output and then hangs forever instead of exiting.
- **Recording is per session, not per account.** Pass `recording: true` when you
create the session; without it the replay endpoint 404s forever. The upload is
async after release, so poll for ~30s before giving up.
- **Sandbox commands are not shell-interpreted.** `run("ls -la")` looks for a
binary named `ls -la`. Put argv in `args`, or run `sh -c` explicitly.
- `kill()`**, not** `close()`**, ends a VM.** `close()` drops your local control
channel; the VM keeps running until its idle timeout.
- `timeoutMs` **is a rolling idle window**, not a hard deadline — it resets on
every use.

## Links

- Docs — [docs.getsolari.com](https://docs.getsolari.com)
- Console — [console.getsolari.com](https://console.getsolari.com)
- Changelog — [changelog.getsolari.com](https://changelog.getsolari.com)
- Questions — [hello@getsolari.com](mailto:hello@getsolari.com)

## Contributing

New examples are welcome. Keep them small, make them run end-to-end against the
real API, and put anything surprising in a comment right where it bites.

MIT licensed.
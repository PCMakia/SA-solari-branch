# Sleeper AFK Overseer

**Sleeper AFK Overseer** is a full-stack agent demo on [Solari](https://getsolari.com): give one
initiate command from Cursor, step away, and the overseer runs your task queue on Solari
sandboxes and browsers while managing retries and surfacing `NEEDS_REPAIR` when code needs a fix.

This repo is a monorepo:

| Path | Role |
|------|------|
| [packages/sleeper-mcp](packages/sleeper-mcp) | MCP server — queue, Solari/Docker backends, `start_afk_overseer` |
| [apps/overseer-dashboard](apps/overseer-dashboard) | Next.js UI — live queue, terminal output, replay placeholder |
| [examples/](examples) | Upstream Solari cookbook quickstarts |
| [docs/OVERSEER.md](docs/OVERSEER.md) | Architecture and MCP tool reference |
| [docs/TESTING.md](docs/TESTING.md) | Step-by-step test guide |
| [docs/mcp.json.example](docs/mcp.json.example) | Copy-paste Cursor MCP config |

## Quick start

### 1. Install MCP dependencies

```bash
cd packages/sleeper-mcp
pip install -r requirements.txt
```

### 2. Add your Solari API key to Cursor

Copy [docs/mcp.json.example](docs/mcp.json.example) into `%USERPROFILE%\.cursor\mcp.json`
(merge with any existing servers). Replace `slr_live_YOUR_KEY_HERE` with your key from
[console.getsolari.com](https://console.getsolari.com).

The key lives in the MCP server's `env` block — **not** in the Next.js app (unless you add replay routes later).

### 3. Restart Cursor

Reload MCP so `sleeper-agent-mcp` picks up the new config.

### 4. Start the dashboard

```bash
cd apps/overseer-dashboard
npm install
npm run dev
```

Open http://localhost:3000

### 5. Start an overseer session from Cursor

Ask the agent to call `start_afk_overseer` with a task list, for example:

```json
{
  "tasks": [
    { "id": "hello", "command": "python", "args": ["-c", "print('overseer ok')"] },
    {
      "id": "smoke",
      "runtime": "browser",
      "command": "python",
      "args": [],
      "url": "https://example.com"
    }
  ],
  "label": "demo"
}
```

Watch progress on the dashboard and in `get_queue_status`.

Full testing steps: [docs/TESTING.md](docs/TESTING.md)

Pre-publish verification: [docs/PUBLISH_CHECKLIST.md](docs/PUBLISH_CHECKLIST.md)

Repair-loop demo (intentional failure → fix → resume): [docs/REPAIR_LOOP_DEMO.md](docs/REPAIR_LOOP_DEMO.md)

```bash
python packages/sleeper-mcp/scripts/preflight.py --live
```

---

# Solari Cookbook

Short, runnable examples for [Solari](https://getsolari.com) — cloud browsers,
sandboxes, and desktops behind one API key.

Every example in this repo is a complete program you can run in under a minute.
They are deliberately small: one idea each, no framework, no scaffolding to read
past. Copy one into your project and change the parts you care about.

## Examples

### Cloud browser

| Example | Language | What it shows |
| --- | --- | --- |
| [browser-quickstart-ts](examples/browser-quickstart-ts) | TypeScript | Launch a browser, open a page, read it |
| [browser-quickstart-py](examples/browser-quickstart-py) | Python | Launch a browser, open a page, read it |
| [browser-stealth-proxy-ts](examples/browser-stealth-proxy-ts) | TypeScript | Stealth mode + residential proxy egress |
| [browser-profiles-ts](examples/browser-profiles-ts) | TypeScript | Log in once, reuse the session forever |
| [browser-session-recording-py](examples/browser-session-recording-py) | Python | Record a session, download the replay |

### Sandbox

| Example | Language | What it shows |
| --- | --- | --- |
| [sandbox-quickstart-ts](examples/sandbox-quickstart-ts) | TypeScript | Run a command, write and read files |
| [sandbox-code-interpreter-py](examples/sandbox-code-interpreter-py) | Python | Stateful Python kernel for agent loops |
| [sandbox-port-preview-ts](examples/sandbox-port-preview-ts) | TypeScript | Expose a server in the VM on a public URL |

### Desktop

| Example | Language | What it shows |
| --- | --- | --- |
| [desktop-computer-use-py](examples/desktop-computer-use-py) | Python | Screenshot, click, and type on a Linux GUI |

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

- **TypeScript: call `await solari.close()`.** The browser client keeps a
  loopback proxy open for connection retries. Skip the close and your script
  prints its output and then hangs forever instead of exiting.
- **Recording is per session, not per account.** Pass `recording: true` when you
  create the session; without it the replay endpoint 404s forever. The upload is
  async after release, so poll for ~30s before giving up.
- **Sandbox commands are not shell-interpreted.** `run("ls -la")` looks for a
  binary named `ls -la`. Put argv in `args`, or run `sh -c` explicitly.
- **`kill()`, not `close()`, ends a VM.** `close()` drops your local control
  channel; the VM keeps running until its idle timeout.
- **`timeoutMs` is a rolling idle window**, not a hard deadline — it resets on
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

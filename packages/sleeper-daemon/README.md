# sleeper-daemon

Local AFK companion for **Sleeper AFK Overseer**. Watches a project’s `.sleeper_input`
and `.sleeper/events.jsonl`, pastes kickoff/repair prompts into Cursor chat, and
ensures the overseer dashboard is reachable.

Usually started automatically by `start_afk_overseer` (see
[../sleeper-mcp/install/](../sleeper-mcp/install/)). Manual run:

```bash
cd packages/sleeper-daemon
pip install -e . -r requirements.txt
python -m sleeper_daemon.cli watch --workspace C:/path/to/your/project --window-title Cursor
```

`workspace` is the **user project**, not the Solari clone (`SLEEPER_HOME`).

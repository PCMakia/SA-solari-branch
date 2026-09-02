#!/usr/bin/env python3
"""Pre-publish verification for Sleeper AFK Overseer."""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
ROOT = PKG.parent.parent
DASHBOARD = ROOT / "apps" / "overseer-dashboard"


def _run(cmd: list[str], *, cwd: Path, label: str) -> None:
    print(f"\n==> {label}")
    print("    ", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def _check_env() -> dict[str, bool]:
    key = os.environ.get("SOLARI_API_KEY", "").strip()
    checks = {
        "SOLARI_API_KEY_set": bool(key),
        "SLEEPER_BACKEND": os.environ.get("SLEEPER_BACKEND", "docker") == "solari",
    }
    print("\n==> Environment")
    for name, ok in checks.items():
        print(f"    {'PASS' if ok else 'SKIP'} {name}")
    return checks


async def _list_mcp_tools() -> list:
    from sleeper_agent_mcp.server import mcp

    return await mcp.list_tools()


def _check_imports() -> None:
    print("\n==> Python imports")
    sys.path.insert(0, str(PKG))
    from sleeper_agent_mcp.backends import get_execution_backend, run_task  # noqa: F401
    from sleeper_agent_mcp.server import SERVER_BUILD

    tools = asyncio.run(_list_mcp_tools())
    print(f"    server_build={SERVER_BUILD}")
    print(f"    tools={len(tools)} {[t.name for t in tools]}")


async def _live_sandbox_smoke() -> None:
    from solari_sandbox import SandboxClient

    api_key = os.environ["SOLARI_API_KEY"]
    base_url = os.environ.get("SOLARI_BASE_URL", "https://api.getsolari.com")
    print("\n==> Live Solari sandbox (run_code)")

    async with SandboxClient(api_key=api_key, base_url=base_url) as client:
        sandbox = await client.create(template="base", timeout_ms=5 * 60_000)
        try:
            await sandbox.connect()
            result = await sandbox.run_code("print(42)")
            if result.error:
                raise RuntimeError(f"run_code error: {result.error}")
            text = "".join(
                item.text for item in result.results if getattr(item, "text", None)
            )
            if "42" not in text:
                raise RuntimeError(f"unexpected output: {text!r}")
            print("    PASS sandbox run_code print(42)")
        finally:
            await sandbox.kill()


async def _live_browser_smoke() -> None:
    from solari_browser import Solari

    api_key = os.environ["SOLARI_API_KEY"]
    print("\n==> Live Solari browser (example.com)")

    solari = Solari(api_key=api_key)
    browser = await solari.launch(recording=True)
    try:
        page = await browser.new_page()
        await page.goto("https://example.com")
        title = await page.title()
        await asyncio.sleep(1)
        if not title:
            raise RuntimeError("empty page title")
        print(f"    PASS browser title={title!r} session={browser.id}")
    finally:
        await browser.close()
        # Required: stops the local Playwright/proxy subprocess (see Solari cookbook).
        await solari.close()


async def _run_live_checks() -> None:
    await _live_sandbox_smoke()
    await _live_browser_smoke()
    # Give Windows Proactor event loop time to close pipe transports cleanly.
    await asyncio.sleep(0.25)


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-publish checks")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run live Solari API smoke tests (requires SOLARI_API_KEY)",
    )
    parser.add_argument(
        "--skip-dashboard",
        action="store_true",
        help="Skip npm run build",
    )
    args = parser.parse_args()

    print(f"Root: {ROOT}")

    _run([sys.executable, "-m", "compileall", "sleeper_agent_mcp"], cwd=PKG, label="compileall")
    _run([sys.executable, "-m", "pytest", "tests", "-q"], cwd=PKG, label="pytest")

    if not args.skip_dashboard:
        npm = "npm.cmd" if sys.platform == "win32" else "npm"
        next_dir = DASHBOARD / ".next"
        if next_dir.exists():
            import shutil

            shutil.rmtree(next_dir)
        _run([npm, "run", "build"], cwd=DASHBOARD, label="dashboard build")

    _check_imports()
    env = _check_env()

    if args.live:
        if not env["SOLARI_API_KEY_set"]:
            print("\nFAIL --live requires SOLARI_API_KEY in environment")
            return 1
        asyncio.run(_run_live_checks())

    print("\n" + "=" * 50)
    print("PREFLIGHT PASSED")
    if not args.live:
        print("Tip: run with --live after exporting SOLARI_API_KEY for full API checks")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

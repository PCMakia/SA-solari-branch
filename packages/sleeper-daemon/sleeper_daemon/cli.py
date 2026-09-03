#!/usr/bin/env python3
"""Standalone Sleeper daemon for local Cursor overseer workflows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sleeper_daemon.daemon import DaemonConfig, SleeperDaemon
from sleeper_daemon.windows import get_active_cursor_windows


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        default=".",
        help="Target workspace root (default: current directory)",
    )
    parser.add_argument(
        "--driver",
        choices=["host", "solari"],
        default="host",
        help="Cursor UI driver (default: host)",
    )
    parser.add_argument(
        "--window-title",
        default="",
        help="Substring to match Cursor window title",
    )
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--turn-timeout-seconds", type=float, default=900.0)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sleeper local Cursor overseer daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python sleeper_daemon.py windows\n"
            "  python sleeper_daemon.py watch --workspace D:/project --window-title Solari\n"
            "  python sleeper_daemon.py run --workspace D:/project --file payload.txt\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser(
        "run",
        help="Process one Sleeper-call payload and watch to completion",
    )
    _add_common_args(run_cmd)
    run_cmd.add_argument("payload", nargs="?", default="", help="Sleeper-call wrapped text")
    run_cmd.add_argument("--file", default="", help="Read payload from a file instead of argv")
    run_cmd.add_argument("--label", default="sleeper-session")

    watch_cmd = sub.add_parser(
        "watch",
        help="Watch .sleeper_input in the workspace for new payloads",
    )
    _add_common_args(watch_cmd)

    windows_cmd = sub.add_parser(
        "windows",
        help="List Cursor windows on the host",
    )
    _add_common_args(windows_cmd)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "windows":
        windows = [
            {"hwnd": window.hwnd, "title": window.title, "pid": window.pid}
            for window in get_active_cursor_windows()
        ]
        sys.stdout.write(json.dumps(windows, indent=2) + "\n")
        return 0

    config = DaemonConfig(
        workspace=args.workspace,
        poll_seconds=args.poll_seconds,
        turn_timeout_seconds=args.turn_timeout_seconds,
        driver_name=args.driver,
        window_title=args.window_title or None,
    )
    daemon = SleeperDaemon(config)

    if args.command == "watch":
        daemon.watch_input_file()
        return 0

    if args.command == "run":
        payload = args.payload
        if args.file:
            payload = Path(args.file).read_text(encoding="utf-8")
        if not payload.strip():
            input_path = Path(config.workspace) / ".sleeper_input"
            if input_path.is_file():
                payload = input_path.read_text(encoding="utf-8")
        if not payload.strip():
            parser.error("Provide a Sleeper-call payload via argument, --file, or .sleeper_input")
        daemon.run_payload(payload, label=args.label)
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

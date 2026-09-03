#!/usr/bin/env python3
"""Compatibility entrypoint for `python sleeper_daemon.py ...`."""

from sleeper_daemon.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

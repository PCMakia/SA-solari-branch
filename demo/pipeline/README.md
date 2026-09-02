"""Three-step pipeline demo for AFK overseer repair loops.

Run via start_afk_overseer with all three scripts. One step fails mid-chain;
the agent discovers which from NEEDS_REPAIR (not from the start prompt).
"""

# Task chain for start_afk_overseer:
# [
#   {"id": "ingest", "command": "python", "args": ["demo/pipeline/ingest.py"]},
#   {"id": "transform", "command": "python", "args": ["demo/pipeline/transform.py"]},
#   {"id": "export", "command": "python", "args": ["demo/pipeline/export.py"]},
# ]

"""Intentionally broken script for the AFK overseer repair-loop demo.

Run via start_afk_overseer, wait for NEEDS_REPAIR, fix the typo below,
then call resume_queue.
"""


def add(a: int, b: int) -> int:
    return a + b


def main() -> None:
    print(add(2, 3))


if __name__ == "__main__":
    main()

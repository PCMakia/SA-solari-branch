"""Pipeline step 2 — aggregate ingested records."""

RECORDS = [10, 20, 30]


def compute_total(values: list[int]) -> int:
    return sum(values)


def main() -> None:
    total = compute_total(RECORDS)
    print(f"transform: total={total}")


if __name__ == "__main__":
    main()

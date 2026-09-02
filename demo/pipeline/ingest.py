"""Pipeline step 1 — load sample records."""

RECORDS = [10, 20, 30]


def main() -> None:
    print(f"ingest: loaded {len(RECORDS)} records")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
from pathlib import Path


def main() -> None:
    fixture_dir = Path("data/fixtures")
    print(f"Evaluation scaffold. Fixture dir: {fixture_dir.resolve()}")


if __name__ == "__main__":
    main()

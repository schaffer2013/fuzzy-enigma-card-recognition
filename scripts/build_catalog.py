#!/usr/bin/env python
from card_engine.catalog.build_catalog import build_catalog


if __name__ == "__main__":
    path = build_catalog("data/catalog/cards.sqlite3")
    print(f"Catalog ready at {path}")

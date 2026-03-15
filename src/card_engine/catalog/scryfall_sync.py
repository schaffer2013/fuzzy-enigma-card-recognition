from pathlib import Path


def sync_bulk_data(output_path: str) -> Path:
    """Placeholder sync entry point."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[]\n", encoding="utf-8")
    return path

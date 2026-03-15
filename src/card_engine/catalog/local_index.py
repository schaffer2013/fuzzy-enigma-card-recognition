from dataclasses import dataclass


@dataclass
class CatalogRecord:
    name: str
    normalized_name: str
    set_code: str | None = None
    collector_number: str | None = None
    layout: str | None = None

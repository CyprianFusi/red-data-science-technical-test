"""Load reference CSVs into per-entity-type gazetteers for mention matching."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from pipeline.textutils import normalize_text

REFERENCE_FILES: dict[str, str] = {
    "lrf": "lrfs.csv",
    "incident": "incidents.csv",
    "organisation": "organisations.csv",
    "site": "sites.csv",
}

ID_COLUMNS: dict[str, str] = {
    "lrf": "lrf_id",
    "incident": "incident_id",
    "organisation": "org_id",
    "site": "site_id",
}


@dataclass(frozen=True)
class ReferenceEntity:
    entity_id: str
    entity_type: str
    name: str
    aliases: tuple[str, ...]


@dataclass
class Gazetteer:
    entity_type: str
    entities_by_id: dict[str, ReferenceEntity]
    lookup: dict[str, str]


def load_gazetteer(reference_dir: Path, entity_type: str) -> Gazetteer:
    id_column = ID_COLUMNS[entity_type]
    csv_path = reference_dir / REFERENCE_FILES[entity_type]

    entities_by_id: dict[str, ReferenceEntity] = {}
    lookup: dict[str, str] = {}

    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            entity_id = row[id_column].strip()
            name = row["name"].strip()
            aliases_raw = (row.get("aliases") or "").strip()
            aliases = tuple(a.strip() for a in aliases_raw.split("|") if a.strip())

            entities_by_id[entity_id] = ReferenceEntity(
                entity_id=entity_id, entity_type=entity_type, name=name, aliases=aliases
            )
            lookup[normalize_text(name)] = entity_id
            for alias in aliases:
                lookup[normalize_text(alias)] = entity_id

    return Gazetteer(entity_type=entity_type, entities_by_id=entities_by_id, lookup=lookup)


def load_all_gazetteers(reference_dir: Path) -> dict[str, Gazetteer]:
    return {entity_type: load_gazetteer(reference_dir, entity_type) for entity_type in REFERENCE_FILES}

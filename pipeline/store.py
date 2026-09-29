"""Write the accumulated pipeline output to SQLite plus CSV dumps."""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from pipeline.emails import ParsedEmail
from pipeline.observations import Observation
from pipeline.relations import Relation
from pipeline.resolve import ResolvedEntity

_SCHEMA = """
CREATE TABLE source_emails (
    message_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    from_addr TEXT,
    date TEXT,
    subject TEXT
);
CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    is_new INTEGER NOT NULL,
    first_seen_email TEXT
);
CREATE TABLE entity_aliases (
    entity_id TEXT NOT NULL,
    alias_text TEXT NOT NULL,
    source_email TEXT NOT NULL
);
CREATE TABLE relations (
    id INTEGER PRIMARY KEY,
    relation_type TEXT NOT NULL,
    from_entity_id TEXT NOT NULL,
    to_entity_id TEXT NOT NULL,
    source_email TEXT NOT NULL,
    observed_at TEXT
);
CREATE TABLE observations (
    id INTEGER PRIMARY KEY,
    entity_id TEXT NOT NULL,
    property TEXT NOT NULL,
    value TEXT NOT NULL,
    observed_at TEXT,
    source_email TEXT NOT NULL,
    snippet TEXT
);
"""


def _iso(dt) -> str | None:
    return dt.isoformat() if dt is not None else None


def write_output(
    out_dir: Path,
    emails: list[ParsedEmail],
    entities: list[ResolvedEntity],
    aliases: list[tuple[str, str, str]],
    first_seen: dict[str, str],
    relations: list[Relation],
    observations: list[Observation],
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "pipeline.db"
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)

    conn.executemany(
        "INSERT INTO source_emails VALUES (?, ?, ?, ?, ?)",
        [(e.message_id, str(e.path), e.from_addr, _iso(e.date), e.subject) for e in emails],
    )
    conn.executemany(
        "INSERT INTO entities VALUES (?, ?, ?, ?, ?)",
        [
            (e.entity_id, e.entity_type, e.canonical_name, int(e.is_new), first_seen.get(e.entity_id))
            for e in sorted(entities, key=lambda e: e.entity_id)
        ],
    )
    conn.executemany("INSERT INTO entity_aliases VALUES (?, ?, ?)", aliases)
    conn.executemany(
        "INSERT INTO relations (relation_type, from_entity_id, to_entity_id, source_email, observed_at) VALUES (?, ?, ?, ?, ?)",
        [(r.relation_type, r.from_entity.entity_id, r.to_entity.entity_id, r.source_email, _iso(r.observed_at)) for r in relations],
    )
    conn.executemany(
        "INSERT INTO observations (entity_id, property, value, observed_at, source_email, snippet) VALUES (?, ?, ?, ?, ?, ?)",
        [(o.entity.entity_id, o.property, o.value, _iso(o.observed_at), o.source_email, o.snippet) for o in observations],
    )
    conn.commit()

    _dump_csv(conn, out_dir / "csv")
    conn.close()
    return db_path


_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")


def _neutralize_formula_cell(value):
    if isinstance(value, str) and value.startswith(_FORMULA_TRIGGER_CHARS):
        return "'" + value
    return value


def _dump_csv(conn: sqlite3.Connection, csv_dir: Path) -> None:
    csv_dir.mkdir(parents=True, exist_ok=True)
    for table in ["source_emails", "entities", "entity_aliases", "relations", "observations"]:
        cursor = conn.execute(f"SELECT * FROM {table}")
        columns = [d[0] for d in cursor.description]
        with open(csv_dir / f"{table}.csv", "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(columns)
            for row in cursor.fetchall():
                writer.writerow([_neutralize_formula_cell(v) for v in row])

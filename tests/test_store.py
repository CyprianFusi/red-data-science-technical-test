import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from pipeline.emails import ParsedEmail
from pipeline.relations import Relation
from pipeline.observations import Observation
from pipeline.resolve import ResolvedEntity
from pipeline.store import write_output

SITE = ResolvedEntity("SITE-0001", "site", "A591", is_new=False)
INCIDENT = ResolvedEntity("INC-001", "incident", "Storm Fenella", is_new=False)
WHEN = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)


def _sample_email(tmp_path):
    path = tmp_path / "email-1.eml"
    path.write_text("dummy")
    return ParsedEmail(path=path, message_id="msg-1", from_addr="a@b.com", date=WHEN, subject="Subj", text="body")


def test_write_output_creates_sqlite_db_with_all_tables(tmp_path):
    out_dir = tmp_path / "out"
    email = _sample_email(tmp_path)
    relation = Relation("AFFECTS", INCIDENT, SITE, "email-1.eml", WHEN, "closed the A591")
    observation = Observation(SITE, "status", "closed", WHEN, "email-1.eml", "A591 is closed")

    db_path = write_output(
        out_dir,
        emails=[email],
        entities=[SITE, INCIDENT],
        aliases=[("SITE-0001", "A591 rd", "email-1.eml")],
        first_seen={"SITE-0001": "email-1.eml", "INC-001": "email-1.eml"},
        relations=[relation],
        observations=[observation],
    )

    assert db_path == out_dir / "pipeline.db"
    conn = sqlite3.connect(db_path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"source_emails", "entities", "entity_aliases", "relations", "observations"}

    entities = conn.execute("SELECT id, type, canonical_name, is_new, first_seen_email FROM entities ORDER BY id").fetchall()
    assert entities == [
        ("INC-001", "incident", "Storm Fenella", 0, "email-1.eml"),
        ("SITE-0001", "site", "A591", 0, "email-1.eml"),
    ]

    relations = conn.execute("SELECT relation_type, from_entity_id, to_entity_id, source_email FROM relations").fetchall()
    assert relations == [("AFFECTS", "INC-001", "SITE-0001", "email-1.eml")]

    observations = conn.execute("SELECT entity_id, property, value, source_email FROM observations").fetchall()
    assert observations == [("SITE-0001", "status", "closed", "email-1.eml")]
    conn.close()


def test_write_output_also_dumps_csv_tables(tmp_path):
    out_dir = tmp_path / "out"
    email = _sample_email(tmp_path)
    write_output(out_dir, emails=[email], entities=[SITE], aliases=[], first_seen={"SITE-0001": "email-1.eml"}, relations=[], observations=[])

    csv_dir = out_dir / "csv"
    for name in ["source_emails", "entities", "entity_aliases", "relations", "observations"]:
        assert (csv_dir / f"{name}.csv").exists()

    with open(csv_dir / "entities.csv", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["id"] == "SITE-0001"

import sqlite3
from pathlib import Path

from pipeline.__main__ import run

FIXTURES = Path(__file__).parent / "fixtures"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_run_end_to_end_on_small_fixture_set(tmp_path):
    emails_dir = tmp_path / "emails"
    reference_dir = tmp_path / "reference"
    out_dir = tmp_path / "out"

    _write(
        emails_dir / "e1.eml",
        "From: a@b.com\nTo: c@d.com\nDate: Mon, 12 Jan 2026 10:00:00 +0000\n"
        "Subject: Update\nMessage-ID: <e1@b.com>\nContent-Type: text/plain; charset=\"utf-8\"\n\n"
        "Storm Fenella has closed the A591 between Keswick and Grasmere. "
        "The incident is coordinated by the Cumbria Resilience Forum.\n",
    )
    _write(
        emails_dir / "e2.eml",
        "From: a@b.com\nTo: c@d.com\nDate: Tue, 13 Jan 2026 09:00:00 +0000\n"
        "Subject: Update 2\nMessage-ID: <e2@b.com>\nContent-Type: text/plain; charset=\"utf-8\"\n\n"
        "The A591 has now reopened.\n",
    )
    _write(reference_dir / "lrfs.csv", "lrf_id,name,aliases\nLRF-01,Cumbria Resilience Forum,Cumbria LRF\n")
    _write(reference_dir / "incidents.csv", "incident_id,name,aliases,incident_type,start_date,status\nINC-001,Storm Fenella,,severe_weather,2026-01-12,active\n")
    _write(reference_dir / "organisations.csv", "org_id,name,aliases,org_type,notes\nORG-001,Cumberland Council,,local_authority,\n")
    _write(reference_dir / "sites.csv", "site_id,name,aliases,site_type,locality\nSITE-0001,A591 Keswick to Grasmere,A591,road,Keswick\n")

    summary = run(emails_dir, reference_dir, out_dir)

    assert summary["emails"] == 2
    assert summary["entities"] >= 3
    assert summary["observations"] >= 2

    conn = sqlite3.connect(out_dir / "pipeline.db")
    statuses = conn.execute(
        "SELECT value FROM observations WHERE entity_id='SITE-0001' ORDER BY observed_at"
    ).fetchall()
    assert ("closed",) in statuses
    assert ("open",) in statuses
    relation_types = {row[0] for row in conn.execute("SELECT relation_type FROM relations")}
    assert "AFFECTS" in relation_types
    assert "COORDINATED_BY" in relation_types
    conn.close()


def test_run_does_not_crash_on_email_with_no_entities(tmp_path):
    emails_dir = tmp_path / "emails"
    reference_dir = tmp_path / "reference"
    out_dir = tmp_path / "out"

    _write(
        emails_dir / "e1.eml",
        "From: a@b.com\nTo: c@d.com\nSubject: Nothing\nMessage-ID: <e1@b.com>\n"
        "Content-Type: text/plain; charset=\"utf-8\"\n\nJust a routine check-in, nothing to report.\n",
    )
    _write(reference_dir / "lrfs.csv", "lrf_id,name,aliases\nLRF-01,Cumbria Resilience Forum,\n")
    _write(reference_dir / "incidents.csv", "incident_id,name,aliases,incident_type,start_date,status\n")
    _write(reference_dir / "organisations.csv", "org_id,name,aliases,org_type,notes\n")
    _write(reference_dir / "sites.csv", "site_id,name,aliases,site_type,locality\n")

    summary = run(emails_dir, reference_dir, out_dir)
    assert summary["emails"] == 1
    assert summary["entities"] == 0


def test_run_does_not_crash_on_emails_with_missing_or_duplicate_message_ids(tmp_path):
    emails_dir = tmp_path / "emails"
    reference_dir = tmp_path / "reference"
    out_dir = tmp_path / "out"

    # Neither email has a Message-ID header, so a naive "message_id or ..."
    # key collides across both when writing source_emails.
    _write(
        emails_dir / "e1.eml",
        "From: a@b.com\nTo: c@d.com\nDate: Mon, 12 Jan 2026 10:00:00 +0000\n"
        "Subject: First\nContent-Type: text/plain; charset=\"utf-8\"\n\n"
        "Storm Fenella update one.\n",
    )
    _write(
        emails_dir / "e2.eml",
        "From: a@b.com\nTo: c@d.com\nDate: Tue, 13 Jan 2026 09:00:00 +0000\n"
        "Subject: Second\nContent-Type: text/plain; charset=\"utf-8\"\n\n"
        "Storm Fenella update two.\n",
    )
    _write(reference_dir / "lrfs.csv", "lrf_id,name,aliases\nLRF-01,Cumbria Resilience Forum,\n")
    _write(reference_dir / "incidents.csv", "incident_id,name,aliases,incident_type,start_date,status\nINC-001,Storm Fenella,,severe_weather,2026-01-12,active\n")
    _write(reference_dir / "organisations.csv", "org_id,name,aliases,org_type,notes\n")
    _write(reference_dir / "sites.csv", "site_id,name,aliases,site_type,locality\n")

    summary = run(emails_dir, reference_dir, out_dir)
    assert summary["emails"] == 2

    conn = sqlite3.connect(out_dir / "pipeline.db")
    assert conn.execute("SELECT COUNT(*) FROM source_emails").fetchone()[0] == 2
    conn.close()


def test_run_reports_ambiguous_gazetteer_keys(tmp_path):
    """Two reference rows sharing a name (a realistic disambiguation trap,
    e.g. the same site name in two different towns) must be surfaced, not
    silently resolved by whichever CSV row happened to load last."""
    emails_dir = tmp_path / "emails"
    reference_dir = tmp_path / "reference"
    out_dir = tmp_path / "out"

    _write(
        emails_dir / "e1.eml",
        "From: a@b.com\nTo: c@d.com\nDate: Mon, 12 Jan 2026 10:00:00 +0000\n"
        "Subject: Update\nMessage-ID: <e1@b.com>\nContent-Type: text/plain; charset=\"utf-8\"\n\n"
        "The Riverside Community Centre remains open.\n",
    )
    _write(reference_dir / "lrfs.csv", "lrf_id,name,aliases\n")
    _write(reference_dir / "incidents.csv", "incident_id,name,aliases,incident_type,start_date,status\n")
    _write(reference_dir / "organisations.csv", "org_id,name,aliases,org_type,notes\n")
    _write(
        reference_dir / "sites.csv",
        "site_id,name,aliases,site_type,locality\n"
        "SITE-A,Riverside Community Centre,,site,Carlisle\n"
        "SITE-B,Riverside Community Centre,,site,Kendal\n",
    )

    summary = run(emails_dir, reference_dir, out_dir)
    assert "riverside community centre" in summary["ambiguous_gazetteer_keys"]


def test_pipeline_source_has_no_hardcoded_scenario_names():
    """Guards spec Review Focus #5: resolution/extraction must be driven
    entirely by --reference and rules/*.yaml, not by this scenario's
    specific entity names, so the private dataset works unmodified."""
    import csv as csv_module

    pipeline_dir = Path(__file__).parent.parent / "pipeline"
    source_files = [
        p for p in pipeline_dir.rglob("*.py") if "rules" not in p.parts
    ]
    source_text = "\n".join(p.read_text(encoding="utf-8").lower() for p in source_files)

    reference_dir = Path(__file__).parent.parent / "data" / "reference"
    if not reference_dir.exists():
        return  # real dataset not present in this checkout; nothing to check

    scenario_names = []
    for csv_name in ["lrfs.csv", "incidents.csv", "organisations.csv", "sites.csv"]:
        with open(reference_dir / csv_name, newline="", encoding="utf-8") as fh:
            for row in csv_module.DictReader(fh):
                name = row["name"].strip()
                if len(name) > 6:  # skip short names prone to accidental substring hits
                    scenario_names.append(name.lower())

    offenders = [name for name in scenario_names if name in source_text]
    assert offenders == [], f"pipeline/ source hardcodes scenario-specific names: {offenders}"

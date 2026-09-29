from pathlib import Path
from datetime import datetime, timezone

from pipeline.emails import parse_eml, parse_eml_folder

FIXTURES = Path(__file__).parent / "fixtures" / "emails"


def test_parse_plain_text_email():
    parsed = parse_eml(FIXTURES / "plain_simple.eml")
    assert parsed.message_id == "e52c9ca532e806e09ad9@cumberland-council.example"
    assert parsed.subject == "RE: Complaint from resident - rest centre"
    assert "Priya Nair" in parsed.from_addr
    assert parsed.date is not None
    assert parsed.date.astimezone(timezone.utc).isoformat().startswith("2026-01-15T10:40:00")
    assert "Many thanks for the update." in parsed.text


def test_parse_multipart_prefers_plain_text_part():
    parsed = parse_eml(FIXTURES / "multipart_alt.eml")
    assert "Storm Fenella" in parsed.text
    assert "<html>" not in parsed.text
    assert "<p>" not in parsed.text


def test_parse_html_only_email_strips_tags():
    parsed = parse_eml(FIXTURES / "html_only.eml")
    assert "A591 remains closed between Keswick and Grasmere" in parsed.text
    assert "<b>" not in parsed.text
    assert "<html>" not in parsed.text


def test_parse_email_with_no_date_header_returns_none():
    parsed = parse_eml(FIXTURES / "no_date.eml")
    assert parsed.date is None
    assert "Body with no Date header" in parsed.text


def test_parse_normalizes_non_utc_offset_to_utc():
    parsed = parse_eml(FIXTURES / "bst_offset.eml")
    assert parsed.date == datetime(2026, 1, 15, 9, 40, tzinfo=timezone.utc)
    # Instant equality alone isn't enough: the ISO string written to
    # storage must also be UTC, since observation ordering (`ORDER BY
    # observed_at`) is a lexicographic string comparison, not a proper
    # datetime comparison, and a +01:00 offset would sort wrongly next
    # to a +00:00 one.
    assert parsed.date.utcoffset().total_seconds() == 0
    assert parsed.date.isoformat() == "2026-01-15T09:40:00+00:00"


def test_parse_strips_quoted_reply_lines():
    parsed = parse_eml(FIXTURES / "quoted_reply.eml")
    assert "Received with thanks." in parsed.text
    assert "SITREP 5" not in parsed.text
    assert "Incident status: ACTIVE" not in parsed.text


def test_parse_eml_folder_returns_all_files_sorted():
    parsed = parse_eml_folder(FIXTURES)
    assert [p.path.name for p in parsed] == sorted(
        [
            "plain_simple.eml",
            "multipart_alt.eml",
            "html_only.eml",
            "no_date.eml",
            "quoted_reply.eml",
            "bst_offset.eml",
        ]
    )

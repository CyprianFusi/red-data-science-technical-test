# Incident Email IE Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `pipeline` package so `python -m pipeline --emails <folder> --reference <folder> --out <folder>` reads `.eml` incident emails, resolves entity mentions against reference CSVs (or mints new entities), extracts relations and dated observations, and writes a queryable SQLite database (plus CSV dumps).

**Architecture:** A linear per-email pipeline (parse -> detect mentions -> resolve entities -> extract relations -> extract observations), with gazetteer-driven entity resolution and two YAML-configured rule tables (relations, observations) as the extensible stage. Results accumulate in memory across all emails, then get written once to SQLite + CSV at the end.

**Tech Stack:** Python 3.13, stdlib `email`/`sqlite3`/`csv`/`re`/`html.parser`, plus `rapidfuzz` (fuzzy string matching) and `pyyaml` (rule tables) as the only runtime dependencies. `pytest` for tests. Managed with `uv`.

**Spec:** `docs/superpowers/specs/2026-09-29-incident-ie-pipeline-design.md`

## Global Constraints

- No hosted LLM / external API call at run time; CPU-only, must work with no network access once dependencies are installed (spec §1, §8).
- Full run on the ~270 provided emails must complete in ~10 minutes on a small machine (spec §1).
- Must run unmodified against a private dataset with different reference CSV rows/IDs — no scenario-specific names or IDs hardcoded anywhere in `pipeline/` (spec §1, §10).
- CLI contract is exactly `python -m pipeline --emails <folder> --reference <folder> --out <folder>` (spec §1).
- Entity resolution must happen before, and independently of, relation/observation extraction (spec §3).
- The relation/observation rule tables (`rules/relations.yaml`, `rules/observations.yaml`) are the designated extensible stage — adding a relation or observation type must be a YAML edit, not a code change (spec §5, §6).
- Reference CSV columns are fixed: `lrfs.csv` (`lrf_id,name,aliases`), `incidents.csv` (`incident_id,name,aliases,incident_type,start_date,status`), `organisations.csv` (`org_id,name,aliases,org_type,notes`), `sites.csv` (`site_id,name,aliases,site_type,locality`); `aliases` is `|`-separated (spec §2).

## Review Focus

- An email with no recognizable entity mentions at all must not crash the run — it should simply contribute zero mentions/relations/observations.
- A missing or unparseable `Date` header must not crash parsing — `observed_at` becomes `None` and downstream code must tolerate that.
- Gazetteer matching must be case-insensitive and must match aliases as well as the canonical `name`, since real emails won't always use the reference list's exact casing.
- Overlapping candidate mentions (e.g. "Cumbria" inside "Cumbria Resilience Forum") must resolve to one longest mention, not two overlapping ones.
- Nothing in `pipeline/` may hard-code this scenario's specific entity names or IDs — resolution and extraction must be driven entirely by the CSVs/YAML passed in at run time, so the private dataset works unmodified.

---

## Task 1: Project setup and shared text utilities

**Files:**
- Modify: `pyproject.toml`
- Create: `pipeline/textutils.py`
- Test: `tests/test_textutils.py`
- Create: `tests/__init__.py` (empty, makes `tests` a package for consistent imports)

**Interfaces:**
- Produces: `normalize_text(text: str) -> str` — lowercases, strips, and collapses internal whitespace to single spaces. Used by every later module that compares surface text to gazetteer keys.

- [ ] **Step 1: Add dependencies**

Run:
```bash
uv add rapidfuzz pyyaml
uv add --dev pytest
```
Expected: `pyproject.toml` gains `rapidfuzz`, `pyyaml` under `[project] dependencies` and `pytest` under a dev group; `uv.lock` is created/updated.

- [ ] **Step 2: Write the failing test**

Create `tests/__init__.py` (empty file).

Create `tests/test_textutils.py`:
```python
from pipeline.textutils import normalize_text


def test_normalize_lowercases_and_strips():
    assert normalize_text("  Cumbria Resilience Forum  ") == "cumbria resilience forum"


def test_normalize_collapses_internal_whitespace():
    assert normalize_text("A591   Keswick\tto Grasmere") == "a591 keswick to grasmere"


def test_normalize_empty_string():
    assert normalize_text("") == ""
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_textutils.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.textutils'`

- [ ] **Step 4: Write minimal implementation**

Create `pipeline/textutils.py`:
```python
"""Shared text normalization used by gazetteer matching and resolution."""
import re

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.strip().lower())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_textutils.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock pipeline/textutils.py tests/__init__.py tests/test_textutils.py
git commit -m "chore: add pipeline dependencies and text normalization helper"
```

---

## Task 2: Email parsing (`pipeline/emails.py`)

**Files:**
- Create: `pipeline/emails.py`
- Test: `tests/test_emails.py`
- Create fixtures: `tests/fixtures/emails/plain_simple.eml`, `tests/fixtures/emails/multipart_alt.eml`, `tests/fixtures/emails/html_only.eml`, `tests/fixtures/emails/no_date.eml`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `ParsedEmail` dataclass with fields `path: Path`, `message_id: str`, `from_addr: str`, `date: datetime | None`, `subject: str`, `text: str`; `parse_eml(path: Path) -> ParsedEmail`; `parse_eml_folder(folder: Path) -> list[ParsedEmail]` (sorted by path name for deterministic ordering). Later tasks read `.text`, `.date`, and use `path`/`message_id` as the observation/relation `source_email` provenance.

- [ ] **Step 1: Write fixture emails**

Create `tests/fixtures/emails/plain_simple.eml`:
```
From: Priya Nair <priya.nair@cumberland-council.example>
To: Karen Ostle <karen.ostle@cumberland-council.example>
Date: Thu, 15 Jan 2026 10:40:00 +0000
Subject: RE: Complaint from resident - rest centre
Message-ID: <e52c9ca532e806e09ad9@cumberland-council.example>
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"
Content-Transfer-Encoding: 7bit

OFFICIAL-SENSITIVE

Many thanks for the update.

Regards,
Priya Nair
```

Create `tests/fixtures/emails/multipart_alt.eml`:
```
From: Sian Pryce <sian.pryce@mhclg.example>
To: RED Duty Officer <red-duty@mhclg.example>
Date: Mon, 12 Jan 2026 16:00:00 +0000
Subject: RED National Sitrep 1
Message-ID: <fd34ad2143266c814f4a@mhclg.example>
MIME-Version: 1.0
Content-Type: multipart/alternative;
 boundary="===============BOUNDARY=="

--===============BOUNDARY==
Content-Type: text/plain; charset="utf-8"

Storm Fenella - Status: Pre-incident monitoring
Lead: Cumbria Resilience Forum

--===============BOUNDARY==
Content-Type: text/html; charset="utf-8"

<html><body><p>Storm Fenella - Status: Pre-incident monitoring<br>Lead: Cumbria Resilience Forum</p></body></html>

--===============BOUNDARY==--
```

Create `tests/fixtures/emails/html_only.eml`:
```
From: Ops <ops@example.com>
To: Duty <duty@example.com>
Date: Tue, 13 Jan 2026 09:00:00 +0000
Subject: Update
Message-ID: <html-only-1@example.com>
MIME-Version: 1.0
Content-Type: text/html; charset="utf-8"

<html><body><p>The A591 remains <b>closed</b> between Keswick and Grasmere.</p></body></html>
```

Create `tests/fixtures/emails/no_date.eml`:
```
From: Ops <ops@example.com>
To: Duty <duty@example.com>
Subject: No date header
Message-ID: <no-date-1@example.com>
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"

Body with no Date header at all.
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_emails.py`:
```python
from pathlib import Path
from datetime import timezone

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


def test_parse_eml_folder_returns_all_files_sorted():
    parsed = parse_eml_folder(FIXTURES)
    assert [p.path.name for p in parsed] == sorted(
        ["plain_simple.eml", "multipart_alt.eml", "html_only.eml", "no_date.eml"]
    )
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_emails.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.emails'`

- [ ] **Step 4: Write minimal implementation**

Create `pipeline/emails.py`:
```python
"""Parse .eml files into plain text + headers for downstream extraction."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path


@dataclass
class ParsedEmail:
    path: Path
    message_id: str
    from_addr: str
    date: datetime | None
    subject: str
    text: str


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def get_text(self) -> str:
        return " ".join(chunk.strip() for chunk in self._chunks if chunk.strip())


def _html_to_text(html: str) -> str:
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


def parse_eml(path: Path) -> ParsedEmail:
    with open(path, "rb") as fh:
        msg = BytesParser(policy=policy.default).parse(fh)

    body_part = msg.get_body(preferencelist=("plain", "html"))
    if body_part is None:
        text = ""
    else:
        content = body_part.get_content()
        text = _html_to_text(content) if body_part.get_content_type() == "text/html" else content

    date_header = msg.get("Date")
    date: datetime | None
    try:
        date = parsedate_to_datetime(date_header) if date_header else None
    except (TypeError, ValueError):
        date = None

    return ParsedEmail(
        path=path,
        message_id=(msg.get("Message-ID") or "").strip("<>"),
        from_addr=msg.get("From") or "",
        date=date,
        subject=msg.get("Subject") or "",
        text=text.strip(),
    )


def parse_eml_folder(folder: Path) -> list[ParsedEmail]:
    paths = sorted(folder.glob("*.eml"), key=lambda p: p.name)
    return [parse_eml(p) for p in paths]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_emails.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add pipeline/emails.py tests/test_emails.py tests/fixtures/emails
git commit -m "feat: parse .eml files into plain text with header metadata"
```

---

## Task 3: Reference gazetteers (`pipeline/reference.py`)

**Files:**
- Create: `pipeline/reference.py`
- Test: `tests/test_reference.py`
- Create fixtures: `tests/fixtures/reference/lrfs.csv`, `tests/fixtures/reference/incidents.csv`, `tests/fixtures/reference/organisations.csv`, `tests/fixtures/reference/sites.csv`

**Interfaces:**
- Consumes: `normalize_text` from `pipeline.textutils` (Task 1).
- Produces: `ReferenceEntity` dataclass (`entity_id: str`, `entity_type: str`, `name: str`, `aliases: tuple[str, ...]`); `Gazetteer` dataclass (`entity_type: str`, `entities_by_id: dict[str, ReferenceEntity]`, `lookup: dict[str, str]` — normalized name/alias -> `entity_id`); `load_gazetteer(reference_dir: Path, entity_type: str) -> Gazetteer`; `load_all_gazetteers(reference_dir: Path) -> dict[str, Gazetteer]`; module constants `REFERENCE_FILES: dict[str, str]` and `ID_COLUMNS: dict[str, str]` keyed by entity type (`lrf`, `incident`, `organisation`, `site`). Task 4/5 build mention detection and resolution on top of `Gazetteer.lookup` and `.entities_by_id`.

- [ ] **Step 1: Write fixture reference CSVs**

Create `tests/fixtures/reference/lrfs.csv`:
```
lrf_id,name,aliases
LRF-01,Cumbria Local Resilience Forum,Cumbria LRF|Cumbria Resilience Forum
LRF-02,Lancashire Local Resilience Forum,Lancashire LRF
```

Create `tests/fixtures/reference/incidents.csv`:
```
incident_id,name,aliases,incident_type,start_date,status
INC-001,Storm Fenella,,severe_weather,2026-01-12,active
```

Create `tests/fixtures/reference/organisations.csv`:
```
org_id,name,aliases,org_type,notes
ORG-001,Cumberland Council,,local_authority,
```

Create `tests/fixtures/reference/sites.csv`:
```
site_id,name,aliases,site_type,locality
SITE-0001,A591 Keswick to Grasmere,A591,road,Keswick
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_reference.py`:
```python
from pathlib import Path

from pipeline.reference import load_all_gazetteers, load_gazetteer

FIXTURES = Path(__file__).parent / "fixtures" / "reference"


def test_load_gazetteer_indexes_name_and_aliases():
    gaz = load_gazetteer(FIXTURES, "lrf")
    assert gaz.entity_type == "lrf"
    assert gaz.lookup["cumbria local resilience forum"] == "LRF-01"
    assert gaz.lookup["cumbria lrf"] == "LRF-01"
    assert gaz.lookup["cumbria resilience forum"] == "LRF-01"
    assert gaz.entities_by_id["LRF-01"].name == "Cumbria Local Resilience Forum"
    assert gaz.entities_by_id["LRF-01"].aliases == ("Cumbria LRF", "Cumbria Resilience Forum")


def test_load_gazetteer_handles_empty_aliases_column():
    gaz = load_gazetteer(FIXTURES, "incident")
    assert gaz.entities_by_id["INC-001"].aliases == ()
    assert gaz.lookup["storm fenella"] == "INC-001"


def test_load_all_gazetteers_returns_all_four_types():
    gazetteers = load_all_gazetteers(FIXTURES)
    assert set(gazetteers) == {"lrf", "incident", "organisation", "site"}
    assert gazetteers["site"].lookup["a591"] == "SITE-0001"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_reference.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.reference'`

- [ ] **Step 4: Write minimal implementation**

Create `pipeline/reference.py`:
```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_reference.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add pipeline/reference.py tests/test_reference.py tests/fixtures/reference
git commit -m "feat: load reference CSVs into per-type gazetteers"
```

---

## Task 4: Mention detection (`pipeline/extract.py`)

**Files:**
- Create: `pipeline/extract.py`
- Test: `tests/test_extract.py`

**Interfaces:**
- Consumes: `Gazetteer` from `pipeline.reference` (Task 3); `normalize_text` from `pipeline.textutils` (Task 1).
- Produces: `Mention` dataclass (`entity_type: str`, `surface_text: str`, `start: int`, `end: int`, `matched_entity_id: str | None`); `find_mentions(text: str, gazetteers: dict[str, Gazetteer]) -> list[Mention]` (sorted by `start`, non-overlapping, longest-match-first; `matched_entity_id` set for gazetteer hits, `None` for regex-fallback candidates). Task 5 resolves each `Mention` to an entity id.

- [ ] **Step 1: Write the failing test**

Create `tests/test_extract.py`:
```python
from pipeline.extract import find_mentions
from pipeline.reference import Gazetteer, ReferenceEntity


def _gaz(entity_type, entries):
    entities_by_id = {}
    lookup = {}
    for entity_id, name, aliases in entries:
        entities_by_id[entity_id] = ReferenceEntity(entity_id, entity_type, name, tuple(aliases))
        lookup[name.lower()] = entity_id
        for alias in aliases:
            lookup[alias.lower()] = entity_id
    return Gazetteer(entity_type=entity_type, entities_by_id=entities_by_id, lookup=lookup)


GAZETTEERS = {
    "lrf": _gaz("lrf", [("LRF-01", "cumbria resilience forum", ["cumbria lrf"])]),
    "incident": _gaz("incident", [("INC-001", "storm fenella", [])]),
    "organisation": _gaz("organisation", [("ORG-001", "cumberland council", [])]),
    "site": _gaz("site", [("SITE-0001", "a591 keswick to grasmere", ["a591"])]),
}


def test_finds_exact_gazetteer_match_case_insensitively():
    mentions = find_mentions("Storm Fenella is ongoing.", GAZETTEERS)
    assert len(mentions) == 1
    assert mentions[0].entity_type == "incident"
    assert mentions[0].matched_entity_id == "INC-001"
    assert mentions[0].surface_text == "Storm Fenella"


def test_finds_alias_match():
    mentions = find_mentions("Coordinated by the Cumbria LRF today.", GAZETTEERS)
    assert any(m.matched_entity_id == "LRF-01" for m in mentions)


def test_prefers_longest_overlapping_match():
    mentions = find_mentions(
        "The Cumbria Resilience Forum met this morning.", GAZETTEERS
    )
    lrf_mentions = [m for m in mentions if m.entity_type == "lrf"]
    assert len(lrf_mentions) == 1
    assert lrf_mentions[0].surface_text == "Cumbria Resilience Forum"


def test_regex_fallback_finds_road_not_in_gazetteer():
    mentions = find_mentions("The A585 is closed near Fleetwood.", GAZETTEERS)
    fallback = [m for m in mentions if m.matched_entity_id is None]
    assert any(m.surface_text == "A585" and m.entity_type == "site" for m in fallback)


def test_no_mentions_in_unrelated_text_does_not_crash():
    assert find_mentions("Nothing relevant happened today.", GAZETTEERS) == []


def test_mentions_sorted_by_start_position():
    mentions = find_mentions("Storm Fenella affects the A591.", GAZETTEERS)
    starts = [m.start for m in mentions]
    assert starts == sorted(starts)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_extract.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.extract'`

- [ ] **Step 3: Write minimal implementation**

Create `pipeline/extract.py`:
```python
"""Find candidate entity mentions in email text: gazetteer match first, then
regex fallbacks for entities absent from the reference lists."""
from __future__ import annotations

import re
from dataclasses import dataclass

from pipeline.reference import Gazetteer
from pipeline.textutils import normalize_text


@dataclass
class Mention:
    entity_type: str
    surface_text: str
    start: int
    end: int
    matched_entity_id: str | None


FALLBACK_PATTERNS: dict[str, list[re.Pattern]] = {
    "site": [
        re.compile(r"\bA\d{2,4}\b"),
        re.compile(
            r"\b[A-Z][a-zA-Z'-]*(?:\s+[A-Z][a-zA-Z'-]*){0,3}\s+"
            r"(?:Rest Centre|Treatment Works|Primary School|Leisure Centre|Bridge)\b"
        ),
    ],
    "organisation": [
        re.compile(
            r"\b[A-Z][a-zA-Z'&-]*(?:\s+[A-Z][a-zA-Z'&-]*){0,3}\s+"
            r"(?:Council|Police|Fire and Rescue Service|NHS Trust|Water)\b"
        ),
    ],
    "incident": [
        re.compile(r"\bStorm\s+[A-Z][a-z]+\b"),
    ],
    "lrf": [
        re.compile(
            r"\b[A-Z][a-zA-Z'-]*(?:\s+[A-Z][a-zA-Z'-]*){0,4}\s+"
            r"(?:Local Resilience Forum|LRF)\b"
        ),
    ],
}


def _overlaps(start: int, end: int, accepted: list[tuple[int, int]]) -> bool:
    return any(start < a_end and end > a_start for a_start, a_end in accepted)


def _gazetteer_candidates(text: str, gazetteers: dict[str, Gazetteer]) -> list[Mention]:
    candidates: list[Mention] = []
    for entity_type, gazetteer in gazetteers.items():
        for key in gazetteer.lookup:
            pattern = re.compile(r"\b" + re.escape(key) + r"\b", re.IGNORECASE)
            for match in pattern.finditer(text):
                candidates.append(
                    Mention(
                        entity_type=entity_type,
                        surface_text=match.group(0),
                        start=match.start(),
                        end=match.end(),
                        matched_entity_id=gazetteer.lookup[key],
                    )
                )
    return candidates


def _fallback_candidates(text: str, accepted: list[tuple[int, int]]) -> list[Mention]:
    candidates: list[Mention] = []
    for entity_type, patterns in FALLBACK_PATTERNS.items():
        for pattern in patterns:
            for match in pattern.finditer(text):
                if _overlaps(match.start(), match.end(), accepted):
                    continue
                candidates.append(
                    Mention(
                        entity_type=entity_type,
                        surface_text=match.group(0),
                        start=match.start(),
                        end=match.end(),
                        matched_entity_id=None,
                    )
                )
    return candidates


def find_mentions(text: str, gazetteers: dict[str, Gazetteer]) -> list[Mention]:
    gazetteer_candidates = _gazetteer_candidates(text, gazetteers)
    gazetteer_candidates.sort(key=lambda m: (-(m.end - m.start), m.start))

    accepted: list[Mention] = []
    accepted_spans: list[tuple[int, int]] = []
    for candidate in gazetteer_candidates:
        if _overlaps(candidate.start, candidate.end, accepted_spans):
            continue
        accepted.append(candidate)
        accepted_spans.append((candidate.start, candidate.end))

    fallback = _fallback_candidates(text, accepted_spans)
    for candidate in fallback:
        if _overlaps(candidate.start, candidate.end, accepted_spans):
            continue
        accepted.append(candidate)
        accepted_spans.append((candidate.start, candidate.end))

    accepted.sort(key=lambda m: m.start)
    return accepted
```

Note: `normalize_text` is imported for use by later tasks that build on this module's conventions; `find_mentions` itself matches on raw gazetteer keys (already normalized at load time in Task 3) via case-insensitive regex, so no per-call normalization is needed here.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_extract.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add pipeline/extract.py tests/test_extract.py
git commit -m "feat: detect entity mentions via gazetteer match and regex fallback"
```

---

## Task 5: Entity resolution (`pipeline/resolve.py`)

**Files:**
- Create: `pipeline/resolve.py`
- Test: `tests/test_resolve.py`

**Interfaces:**
- Consumes: `Mention` from `pipeline.extract` (Task 4); `Gazetteer` from `pipeline.reference` (Task 3); `normalize_text` from `pipeline.textutils` (Task 1); `rapidfuzz.fuzz`, `rapidfuzz.process`.
- Produces: `ResolvedEntity` dataclass (`entity_id: str`, `entity_type: str`, `canonical_name: str`, `is_new: bool`); `EntityResolver` class with `__init__(self, gazetteers: dict[str, Gazetteer], fuzzy_threshold: float = 90.0)`, `resolve(self, mention: Mention, source_email: str) -> ResolvedEntity`, `all_entities(self) -> list[ResolvedEntity]`, `aliases(self) -> list[tuple[str, str, str]]` (`entity_id`, `alias_text`, `source_email`), `first_seen(self) -> dict[str, str]` (`entity_id` -> first `source_email` it was resolved from). Task 6/7 call `resolver.resolve(mention, source_email)` for every `Mention` and only ever operate on the returned `ResolvedEntity` objects.

- [ ] **Step 1: Write the failing test**

Create `tests/test_resolve.py`:
```python
from pipeline.extract import Mention
from pipeline.reference import Gazetteer, ReferenceEntity
from pipeline.resolve import EntityResolver


def _gaz(entity_type, entries):
    entities_by_id = {}
    lookup = {}
    for entity_id, name, aliases in entries:
        entities_by_id[entity_id] = ReferenceEntity(entity_id, entity_type, name, tuple(aliases))
        lookup[name.lower()] = entity_id
        for alias in aliases:
            lookup[alias.lower()] = entity_id
    return Gazetteer(entity_type=entity_type, entities_by_id=entities_by_id, lookup=lookup)


GAZETTEERS = {
    "site": _gaz("site", [("SITE-0001", "a591 keswick to grasmere", ["a591"])]),
}


def test_resolve_exact_gazetteer_match_is_not_new():
    resolver = EntityResolver(GAZETTEERS)
    mention = Mention("site", "A591", 0, 4, matched_entity_id="SITE-0001")
    resolved = resolver.resolve(mention, source_email="email-1.eml")
    assert resolved.entity_id == "SITE-0001"
    assert resolved.is_new is False
    assert resolved.canonical_name == "A591 Keswick to Grasmere"


def test_resolve_fuzzy_match_against_gazetteer_reuses_reference_id():
    resolver = EntityResolver(GAZETTEERS, fuzzy_threshold=85.0)
    mention = Mention("site", "A591 Keswick to Grasmear", 0, 25, matched_entity_id=None)
    resolved = resolver.resolve(mention, source_email="email-1.eml")
    assert resolved.entity_id == "SITE-0001"
    assert resolved.is_new is False


def test_resolve_unknown_mention_mints_new_entity():
    resolver = EntityResolver(GAZETTEERS)
    mention = Mention("site", "Penrith Rest Centre", 0, 20, matched_entity_id=None)
    resolved = resolver.resolve(mention, source_email="email-1.eml")
    assert resolved.is_new is True
    assert resolved.entity_id.startswith("SITE-NEW-")
    assert resolved.canonical_name == "Penrith Rest Centre"


def test_resolve_dedups_repeated_new_entity_across_mentions():
    resolver = EntityResolver(GAZETTEERS)
    first = resolver.resolve(
        Mention("site", "Penrith Rest Centre", 0, 20, matched_entity_id=None), "email-1.eml"
    )
    second = resolver.resolve(
        Mention("site", "the Penrith rest centre", 0, 24, matched_entity_id=None), "email-2.eml"
    )
    assert second.entity_id == first.entity_id
    assert len(resolver.all_entities()) == 1


def test_aliases_recorded_for_non_canonical_surface_text():
    resolver = EntityResolver(GAZETTEERS)
    resolver.resolve(Mention("site", "A591", 0, 4, matched_entity_id="SITE-0001"), "email-1.eml")
    aliases = resolver.aliases()
    assert ("SITE-0001", "A591", "email-1.eml") in aliases


def test_first_seen_tracks_earliest_source_email():
    resolver = EntityResolver(GAZETTEERS)
    resolver.resolve(Mention("site", "A591", 0, 4, matched_entity_id="SITE-0001"), "email-1.eml")
    resolver.resolve(Mention("site", "A591", 0, 4, matched_entity_id="SITE-0001"), "email-2.eml")
    assert resolver.first_seen()["SITE-0001"] == "email-1.eml"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_resolve.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.resolve'`

- [ ] **Step 3: Write minimal implementation**

Create `pipeline/resolve.py`:
```python
"""Resolve entity mentions to a single entity id: gazetteer exact/alias
match, fuzzy match, or a freshly minted new-entity id (deduped by fuzzy
match against other new entities created earlier in the same run)."""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz, process

from pipeline.extract import Mention
from pipeline.reference import Gazetteer
from pipeline.textutils import normalize_text

_NEW_ID_PREFIX = {
    "lrf": "LRF-NEW",
    "incident": "INC-NEW",
    "organisation": "ORG-NEW",
    "site": "SITE-NEW",
}


@dataclass
class ResolvedEntity:
    entity_id: str
    entity_type: str
    canonical_name: str
    is_new: bool


class EntityResolver:
    def __init__(self, gazetteers: dict[str, Gazetteer], fuzzy_threshold: float = 90.0) -> None:
        self._gazetteers = gazetteers
        self._fuzzy_threshold = fuzzy_threshold
        self._entity_type: dict[str, str] = {}
        self._canonical_name: dict[str, str] = {}
        self._is_new: dict[str, bool] = {}
        self._first_seen: dict[str, str] = {}
        self._aliases: list[tuple[str, str, str]] = []
        self._new_entities_by_type: dict[str, dict[str, str]] = {}
        self._new_id_counters: dict[str, int] = {}

    def _register(self, entity_id: str, entity_type: str, canonical_name: str, is_new: bool, source_email: str) -> None:
        if entity_id not in self._canonical_name:
            self._entity_type[entity_id] = entity_type
            self._canonical_name[entity_id] = canonical_name
            self._is_new[entity_id] = is_new
            self._first_seen[entity_id] = source_email

    def _record_alias(self, entity_id: str, surface_text: str, source_email: str) -> None:
        canonical = self._canonical_name[entity_id]
        if normalize_text(surface_text) != normalize_text(canonical):
            self._aliases.append((entity_id, surface_text, source_email))

    def _mint_new_entity(self, entity_type: str, surface_text: str, source_email: str) -> ResolvedEntity:
        counter = self._new_id_counters.get(entity_type, 0) + 1
        self._new_id_counters[entity_type] = counter
        entity_id = f"{_NEW_ID_PREFIX[entity_type]}-{counter:03d}"

        self._register(entity_id, entity_type, surface_text, is_new=True, source_email=source_email)
        self._new_entities_by_type.setdefault(entity_type, {})[normalize_text(surface_text)] = entity_id
        return ResolvedEntity(entity_id, entity_type, surface_text, is_new=True)

    def resolve(self, mention: Mention, source_email: str) -> ResolvedEntity:
        gazetteer = self._gazetteers.get(mention.entity_type)

        if mention.matched_entity_id is not None:
            ref_entity = gazetteer.entities_by_id[mention.matched_entity_id]
            self._register(ref_entity.entity_id, ref_entity.entity_type, ref_entity.name, is_new=False, source_email=source_email)
            self._record_alias(ref_entity.entity_id, mention.surface_text, source_email)
            return ResolvedEntity(ref_entity.entity_id, ref_entity.entity_type, ref_entity.name, is_new=False)

        normalized = normalize_text(mention.surface_text)

        if gazetteer is not None and gazetteer.lookup:
            match = process.extractOne(normalized, gazetteer.lookup.keys(), scorer=fuzz.token_sort_ratio)
            if match is not None and match[1] >= self._fuzzy_threshold:
                entity_id = gazetteer.lookup[match[0]]
                ref_entity = gazetteer.entities_by_id[entity_id]
                self._register(ref_entity.entity_id, ref_entity.entity_type, ref_entity.name, is_new=False, source_email=source_email)
                self._record_alias(ref_entity.entity_id, mention.surface_text, source_email)
                return ResolvedEntity(ref_entity.entity_id, ref_entity.entity_type, ref_entity.name, is_new=False)

        existing_new = self._new_entities_by_type.get(mention.entity_type, {})
        if existing_new:
            match = process.extractOne(normalized, existing_new.keys(), scorer=fuzz.token_sort_ratio)
            if match is not None and match[1] >= self._fuzzy_threshold:
                entity_id = existing_new[match[0]]
                self._record_alias(entity_id, mention.surface_text, source_email)
                return ResolvedEntity(entity_id, mention.entity_type, self._canonical_name[entity_id], is_new=True)

        return self._mint_new_entity(mention.entity_type, mention.surface_text, source_email)

    def all_entities(self) -> list[ResolvedEntity]:
        return [
            ResolvedEntity(entity_id, self._entity_type[entity_id], self._canonical_name[entity_id], self._is_new[entity_id])
            for entity_id in self._canonical_name
        ]

    def aliases(self) -> list[tuple[str, str, str]]:
        return list(self._aliases)

    def first_seen(self) -> dict[str, str]:
        return dict(self._first_seen)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_resolve.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add pipeline/resolve.py tests/test_resolve.py
git commit -m "feat: resolve mentions to entities via exact, alias, fuzzy match, or new entity"
```

---

## Task 6: Relation extraction (`pipeline/relations.py`)

**Files:**
- Create: `pipeline/relations.py`
- Create: `pipeline/rules/relations.yaml`
- Test: `tests/test_relations.py`

**Interfaces:**
- Consumes: `Mention` from `pipeline.extract`, `ResolvedEntity` from `pipeline.resolve` (Task 4/5).
- Produces: `Relation` dataclass (`relation_type: str`, `from_entity: ResolvedEntity`, `to_entity: ResolvedEntity`, `source_email: str`, `observed_at: datetime | None`, `snippet: str`); `RELATION_ENTITY_TYPES: dict[str, tuple[str, str]]` (relation type -> `(from_entity_type, to_entity_type)`); `load_relation_rules(path: Path) -> dict[str, list[str]]`; `extract_relations(text: str, resolved_mentions: list[tuple[Mention, ResolvedEntity]], rules: dict[str, list[str]], source_email: str, observed_at: datetime | None, window_chars: int = 400) -> list[Relation]`. Task 9 calls this once per email with that email's mentions.

- [ ] **Step 1: Write the rule table**

Create `pipeline/rules/relations.yaml`:
```yaml
AFFECTS:
  - flooded
  - flooding
  - closed
  - closure
  - disruption
  - affected
  - damaged
COORDINATED_BY:
  - coordinated by
  - chaired by
  - led by
  - multi-agency
RESPONDS_TO:
  - responding to
  - attended
  - deployed to
  - supporting the response
OPERATES:
  - operates
  - runs
  - manages
  - responsible for
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_relations.py`:
```python
from datetime import datetime, timezone

from pipeline.extract import Mention
from pipeline.relations import extract_relations, load_relation_rules
from pipeline.resolve import ResolvedEntity

RULES = {
    "AFFECTS": ["flooded", "closed", "affected"],
    "COORDINATED_BY": ["coordinated by"],
    "RESPONDS_TO": ["responding to"],
    "OPERATES": ["operates"],
}

INCIDENT = ResolvedEntity("INC-001", "incident", "Storm Fenella", is_new=False)
SITE = ResolvedEntity("SITE-0001", "site", "A591", is_new=False)
LRF = ResolvedEntity("LRF-01", "lrf", "Cumbria Resilience Forum", is_new=False)
ORG = ResolvedEntity("ORG-001", "organisation", "Cumberland Council", is_new=False)


def test_extracts_affects_relation_between_incident_and_site():
    text = "Storm Fenella has closed the A591 between Keswick and Grasmere."
    mentions = [
        (Mention("incident", "Storm Fenella", 0, 13, "INC-001"), INCIDENT),
        (Mention("site", "A591", 26, 30, "SITE-0001"), SITE),
    ]
    relations = extract_relations(text, mentions, RULES, "email-1.eml", None)
    assert len(relations) == 1
    assert relations[0].relation_type == "AFFECTS"
    assert relations[0].from_entity.entity_id == "INC-001"
    assert relations[0].to_entity.entity_id == "SITE-0001"


def test_extracts_coordinated_by_relation_between_incident_and_lrf():
    text = "Storm Fenella is coordinated by the Cumbria Resilience Forum."
    mentions = [
        (Mention("incident", "Storm Fenella", 0, 13, "INC-001"), INCIDENT),
        (Mention("lrf", "Cumbria Resilience Forum", 37, 61, "LRF-01"), LRF),
    ]
    relations = extract_relations(text, mentions, RULES, "email-1.eml", None)
    assert relations[0].relation_type == "COORDINATED_BY"


def test_no_relation_when_no_cue_keyword_present():
    text = "Storm Fenella and the A591 were both mentioned in this report."
    mentions = [
        (Mention("incident", "Storm Fenella", 0, 13, "INC-001"), INCIDENT),
        (Mention("site", "A591", 23, 27, "SITE-0001"), SITE),
    ]
    assert extract_relations(text, mentions, RULES, "email-1.eml", None) == []


def test_relation_type_pair_must_match_entity_types():
    text = "Cumberland Council closed the A591."
    mentions = [
        (Mention("organisation", "Cumberland Council", 0, 19, "ORG-001"), ORG),
        (Mention("site", "A591", 31, 35, "SITE-0001"), SITE),
    ]
    relations = extract_relations(text, mentions, RULES, "email-1.eml", None)
    assert relations == []


def test_relation_carries_observed_at_and_source_email():
    when = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
    text = "Storm Fenella has closed the A591."
    mentions = [
        (Mention("incident", "Storm Fenella", 0, 13, "INC-001"), INCIDENT),
        (Mention("site", "A591", 26, 30, "SITE-0001"), SITE),
    ]
    relations = extract_relations(text, mentions, RULES, "email-1.eml", when)
    assert relations[0].observed_at == when
    assert relations[0].source_email == "email-1.eml"


def test_load_relation_rules_reads_yaml(tmp_path):
    rules_file = tmp_path / "relations.yaml"
    rules_file.write_text("AFFECTS:\n  - closed\n  - flooded\n")
    rules = load_relation_rules(rules_file)
    assert rules == {"AFFECTS": ["closed", "flooded"]}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_relations.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.relations'`

- [ ] **Step 4: Write minimal implementation**

Create `pipeline/relations.py`:
```python
"""Rule-based relation extraction: co-occurring resolved entities plus a
cue-keyword table (rules/relations.yaml) decide the relation type. Adding a
relation type is a YAML edit — this table is the pipeline's extensible stage."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from pipeline.extract import Mention
from pipeline.resolve import ResolvedEntity

RELATION_ENTITY_TYPES: dict[str, tuple[str, str]] = {
    "AFFECTS": ("incident", "site"),
    "COORDINATED_BY": ("incident", "lrf"),
    "RESPONDS_TO": ("organisation", "incident"),
    "OPERATES": ("organisation", "site"),
}


@dataclass
class Relation:
    relation_type: str
    from_entity: ResolvedEntity
    to_entity: ResolvedEntity
    source_email: str
    observed_at: datetime | None
    snippet: str


def load_relation_rules(path: Path) -> dict[str, list[str]]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _window(text: str, a: Mention, b: Mention, window_chars: int) -> str | None:
    lo, hi = min(a.start, b.start), max(a.end, b.end)
    if hi - lo > window_chars:
        return None
    return text[max(0, lo - 20): min(len(text), hi + 20)]


def extract_relations(
    text: str,
    resolved_mentions: list[tuple[Mention, ResolvedEntity]],
    rules: dict[str, list[str]],
    source_email: str,
    observed_at: datetime | None,
    window_chars: int = 400,
) -> list[Relation]:
    relations: list[Relation] = []

    for i, (mention_a, entity_a) in enumerate(resolved_mentions):
        for mention_b, entity_b in resolved_mentions[i + 1:]:
            snippet = _window(text, mention_a, mention_b, window_chars)
            if snippet is None:
                continue
            snippet_lower = snippet.lower()

            for relation_type, (from_type, to_type) in RELATION_ENTITY_TYPES.items():
                keywords = rules.get(relation_type, [])
                if not any(keyword.lower() in snippet_lower for keyword in keywords):
                    continue

                if entity_a.entity_type == from_type and entity_b.entity_type == to_type:
                    from_entity, to_entity = entity_a, entity_b
                elif entity_b.entity_type == from_type and entity_a.entity_type == to_type:
                    from_entity, to_entity = entity_b, entity_a
                else:
                    continue

                relations.append(
                    Relation(relation_type, from_entity, to_entity, source_email, observed_at, snippet.strip())
                )

    return relations
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_relations.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: Commit**

```bash
git add pipeline/relations.py pipeline/rules/relations.yaml tests/test_relations.py
git commit -m "feat: extract relations via co-occurrence and cue-keyword rules"
```

---

## Task 7: Observation extraction (`pipeline/observations.py`)

**Files:**
- Create: `pipeline/observations.py`
- Create: `pipeline/rules/observations.yaml`
- Test: `tests/test_observations.py`

**Interfaces:**
- Consumes: `Mention` from `pipeline.extract`, `ResolvedEntity` from `pipeline.resolve`.
- Produces: `Observation` dataclass (`entity: ResolvedEntity`, `property: str`, `value: str`, `observed_at: datetime | None`, `source_email: str`, `snippet: str`); `load_observation_rules(path: Path) -> dict[str, list[tuple[str, str, str]]]` (entity type -> list of `(keyword, property, value)`); `extract_observations(text: str, resolved_mentions: list[tuple[Mention, ResolvedEntity]], rules: dict[str, list[tuple[str, str, str]]], source_email: str, observed_at: datetime | None, window_chars: int = 120) -> list[Observation]`. Task 9 calls this once per email.

- [ ] **Step 1: Write the rule table**

Create `pipeline/rules/observations.yaml`:
```yaml
incident:
  - [stood down, status, closed]
  - [closed, status, closed]
  - [ongoing, status, active]
  - [monitoring, status, monitoring]
  - [escalated, status, escalated]
site:
  - [reopened, status, open]
  - [re-opened, status, open]
  - [closed, status, closed]
  - [flooded, status, affected]
  - [restored, status, restored]
organisation:
  - [stood down, involvement, stood_down]
  - [deployed, involvement, deployed]
lrf:
  - [activated, involvement, activated]
  - [stood down, involvement, stood_down]
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_observations.py`:
```python
from datetime import datetime, timezone

from pipeline.extract import Mention
from pipeline.observations import extract_observations, load_observation_rules
from pipeline.resolve import ResolvedEntity

RULES = {
    "site": [("closed", "status", "closed"), ("reopened", "status", "open")],
    "incident": [("stood down", "status", "closed")],
}

SITE = ResolvedEntity("SITE-0001", "site", "A591", is_new=False)
INCIDENT = ResolvedEntity("INC-001", "incident", "Storm Fenella", is_new=False)


def test_extracts_observation_for_keyword_near_mention():
    text = "The A591 is closed between Keswick and Grasmere."
    mentions = [(Mention("site", "A591", 4, 8, "SITE-0001"), SITE)]
    observations = extract_observations(text, mentions, RULES, "email-1.eml", None)
    assert len(observations) == 1
    assert observations[0].property == "status"
    assert observations[0].value == "closed"
    assert observations[0].entity.entity_id == "SITE-0001"


def test_no_observation_when_keyword_far_from_mention():
    text = "A591. " + ("padding " * 40) + "The road was later reopened."
    mentions = [(Mention("site", "A591", 0, 4, "SITE-0001"), SITE)]
    observations = extract_observations(text, mentions, RULES, "email-1.eml", None, window_chars=30)
    assert observations == []


def test_multiple_entities_each_get_own_observation():
    text = "The A591 is closed. Storm Fenella has been stood down."
    mentions = [
        (Mention("site", "A591", 4, 8, "SITE-0001"), SITE),
        (Mention("incident", "Storm Fenella", 21, 34, "INC-001"), INCIDENT),
    ]
    observations = extract_observations(text, mentions, RULES, "email-1.eml", None)
    values = {(o.entity.entity_id, o.property, o.value) for o in observations}
    assert ("SITE-0001", "status", "closed") in values
    assert ("INC-001", "status", "closed") in values


def test_observation_carries_observed_at_and_source_email():
    when = datetime(2026, 1, 15, tzinfo=timezone.utc)
    text = "The A591 is closed."
    mentions = [(Mention("site", "A591", 4, 8, "SITE-0001"), SITE)]
    observations = extract_observations(text, mentions, RULES, "email-1.eml", when)
    assert observations[0].observed_at == when
    assert observations[0].source_email == "email-1.eml"


def test_load_observation_rules_reads_yaml(tmp_path):
    rules_file = tmp_path / "observations.yaml"
    rules_file.write_text("site:\n  - [closed, status, closed]\n")
    rules = load_observation_rules(rules_file)
    assert rules == {"site": [("closed", "status", "closed")]}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_observations.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.observations'`

- [ ] **Step 4: Write minimal implementation**

Create `pipeline/observations.py`:
```python
"""Rule-based observation extraction: a keyword near a resolved mention maps
to a (property, value) fact via rules/observations.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from pipeline.extract import Mention
from pipeline.resolve import ResolvedEntity


@dataclass
class Observation:
    entity: ResolvedEntity
    property: str
    value: str
    observed_at: datetime | None
    source_email: str
    snippet: str


def load_observation_rules(path: Path) -> dict[str, list[tuple[str, str, str]]]:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return {entity_type: [tuple(rule) for rule in rules] for entity_type, rules in raw.items()}


def extract_observations(
    text: str,
    resolved_mentions: list[tuple[Mention, ResolvedEntity]],
    rules: dict[str, list[tuple[str, str, str]]],
    source_email: str,
    observed_at: datetime | None,
    window_chars: int = 120,
) -> list[Observation]:
    observations: list[Observation] = []

    for mention, entity in resolved_mentions:
        entity_rules = rules.get(mention.entity_type, [])
        if not entity_rules:
            continue

        lo = max(0, mention.start - window_chars)
        hi = min(len(text), mention.end + window_chars)
        window = text[lo:hi]
        window_lower = window.lower()

        for keyword, prop, value in entity_rules:
            if keyword.lower() in window_lower:
                observations.append(
                    Observation(entity, prop, value, observed_at, source_email, window.strip())
                )

    return observations
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_observations.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add pipeline/observations.py pipeline/rules/observations.yaml tests/test_observations.py
git commit -m "feat: extract dated observations via per-entity-type keyword rules"
```

---

## Task 8: SQLite + CSV output (`pipeline/store.py`)

**Files:**
- Create: `pipeline/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `ParsedEmail` (Task 2), `ResolvedEntity` (Task 5), `Relation` (Task 6), `Observation` (Task 7).
- Produces: `write_output(out_dir: Path, emails: list[ParsedEmail], entities: list[ResolvedEntity], aliases: list[tuple[str, str, str]], first_seen: dict[str, str], relations: list[Relation], observations: list[Observation]) -> Path` — creates `out_dir/pipeline.db` (SQLite) with tables `source_emails`, `entities`, `entity_aliases`, `relations`, `observations`, and dumps the same tables as CSV under `out_dir/csv/`. Returns the db path. Task 9's `run()` calls this once at the end.

- [ ] **Step 1: Write the failing test**

Create `tests/test_store.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.store'`

- [ ] **Step 3: Write minimal implementation**

Create `pipeline/store.py`:
```python
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    relation_type TEXT NOT NULL,
    from_entity_id TEXT NOT NULL,
    to_entity_id TEXT NOT NULL,
    source_email TEXT NOT NULL,
    observed_at TEXT
);
CREATE TABLE observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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


def _dump_csv(conn: sqlite3.Connection, csv_dir: Path) -> None:
    csv_dir.mkdir(parents=True, exist_ok=True)
    for table in ["source_emails", "entities", "entity_aliases", "relations", "observations"]:
        cursor = conn.execute(f"SELECT * FROM {table}")
        columns = [d[0] for d in cursor.description]
        with open(csv_dir / f"{table}.csv", "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(columns)
            writer.writerows(cursor.fetchall())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_store.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add pipeline/store.py tests/test_store.py
git commit -m "feat: write pipeline output to SQLite and CSV"
```

---

## Task 9: CLI orchestration (`pipeline/__main__.py`) and end-to-end smoke test

**Files:**
- Modify: `pipeline/__main__.py`
- Modify: `pipeline/__init__.py`
- Test: `tests/test_pipeline_integration.py`

**Interfaces:**
- Consumes: every module from Tasks 2–8.
- Produces: `run(emails_dir: Path, reference_dir: Path, out_dir: Path) -> dict` (returns summary counts: `{"emails": int, "entities": int, "relations": int, "observations": int}`); `main()` (argparse wrapper calling `run`). This is the final integration point — no later task depends on it.

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_pipeline_integration.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_integration.py -v`
Expected: FAIL — `ImportError: cannot import name 'run' from 'pipeline.__main__'`

- [ ] **Step 3: Write the implementation**

Replace `pipeline/__main__.py`:
```python
"""Command-line entry point for the incident email IE pipeline.

Run:
    python -m pipeline --emails data/emails --reference data/reference --out output
"""
from __future__ import annotations

import argparse
from pathlib import Path

from pipeline.emails import parse_eml_folder
from pipeline.extract import find_mentions
from pipeline.observations import extract_observations, load_observation_rules
from pipeline.reference import load_all_gazetteers
from pipeline.relations import extract_relations, load_relation_rules
from pipeline.resolve import EntityResolver
from pipeline.store import write_output

_RULES_DIR = Path(__file__).parent / "rules"


def run(emails_dir: Path, reference_dir: Path, out_dir: Path) -> dict:
    gazetteers = load_all_gazetteers(reference_dir)
    relation_rules = load_relation_rules(_RULES_DIR / "relations.yaml")
    observation_rules = load_observation_rules(_RULES_DIR / "observations.yaml")

    parsed_emails = parse_eml_folder(emails_dir)
    resolver = EntityResolver(gazetteers)
    all_relations = []
    all_observations = []

    for email in parsed_emails:
        source_email = email.message_id or str(email.path.name)
        mentions = find_mentions(email.text, gazetteers)
        resolved = [(mention, resolver.resolve(mention, source_email)) for mention in mentions]

        all_relations.extend(
            extract_relations(email.text, resolved, relation_rules, source_email, email.date)
        )
        all_observations.extend(
            extract_observations(email.text, resolved, observation_rules, source_email, email.date)
        )

    write_output(
        out_dir,
        emails=parsed_emails,
        entities=resolver.all_entities(),
        aliases=resolver.aliases(),
        first_seen=resolver.first_seen(),
        relations=all_relations,
        observations=all_observations,
    )

    return {
        "emails": len(parsed_emails),
        "entities": len(resolver.all_entities()),
        "relations": len(all_relations),
        "observations": len(all_observations),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Incident email IE pipeline")
    parser.add_argument("--emails", required=True, type=Path, help="folder of .eml files")
    parser.add_argument("--reference", required=True, type=Path, help="folder of reference list CSV files")
    parser.add_argument("--out", required=True, type=Path, help="output folder")
    args = parser.parse_args()

    summary = run(args.emails, args.reference, args.out)
    print(
        f"Processed {summary['emails']} emails -> "
        f"{summary['entities']} entities, {summary['relations']} relations, "
        f"{summary['observations']} observations. Output: {args.out}"
    )


if __name__ == "__main__":
    main()
```

Update `pipeline/__init__.py`:
```python
"""Information extraction pipeline for incident emails."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline_integration.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests from Tasks 1–9 PASS.

- [ ] **Step 6: Commit**

```bash
git add pipeline/__main__.py pipeline/__init__.py tests/test_pipeline_integration.py
git commit -m "feat: wire pipeline stages together behind the python -m pipeline CLI"
```

---

## Task 10: Run on the provided dataset and record timing

**Files:**
- No new source files. Produces committed output under `output/`.

- [ ] **Step 1: Run the pipeline on the real data, timing it**

```bash
cd "C:\projects\red-data-science-technical-test"
time uv run python -m pipeline --emails data/emails --reference data/reference --out output
```
Expected: command completes, prints the summary line, and the wall-clock time is well under 10 minutes. Note the measured time (e.g. `real 0mXX.XXXs`) — it goes into `README.md` in Task 11.

- [ ] **Step 2: Sanity-check the output**

Run:
```bash
uv run python -c "
import sqlite3
conn = sqlite3.connect('output/pipeline.db')
for table in ['source_emails', 'entities', 'entity_aliases', 'relations', 'observations']:
    print(table, conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0])
print(conn.execute(\"SELECT type, COUNT(*) FROM entities GROUP BY type\").fetchall())
print(conn.execute(\"SELECT relation_type, COUNT(*) FROM relations GROUP BY relation_type\").fetchall())
"
```
Expected: non-zero counts for entities, relations, and observations, with a plausible split across the four entity types. If any table is empty or one entity type never resolves, investigate before moving on — that is a real defect, not an acceptable result.

- [ ] **Step 3: Commit the output**

```bash
git add output
git commit -m "chore: commit pipeline output for the provided dataset"
```

---

## Task 11: Write `README.md`

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the template**

Fill in every section of the existing `README.md` template (`## Setup`, `## Run`, `## Run time`, `## Extending the pipeline`, `## Private dataset`, `## Assumptions`, `## How I used my time`, `## Use of AI coding assistants`) with real content reflecting what was actually built:
- **Setup**: `uv sync` (installs `rapidfuzz`, `pyyaml`, `pytest` from `pyproject.toml`/`uv.lock`).
- **Run**: the exact CLI command, plus how to point `--emails`/`--reference` at the private dataset later.
- **Run time**: the measured time from Task 10, and the machine it was measured on.
- **Extending the pipeline**: how to add a new relation type (edit `pipeline/rules/relations.yaml` + one line in `RELATION_ENTITY_TYPES` in `pipeline/relations.py`) and a new observation rule (edit `pipeline/rules/observations.yaml`, no code change).
- **Private dataset table**: per spec §10 — gazetteer resolution and rule-driven relation/observation extraction: Yes (driven entirely by files read at run time); regex fallback for new entities: Partly (UK-incident-generic patterns, not scenario-specific, but lower precision than gazetteer matches); anything found to be scenario-specific during implementation: No, with why.
- **Assumptions**: any ambiguity resolved while implementing (e.g. paragraph-based relation/observation windows, fuzzy-match threshold of 90).
- **How I used my time**: honest breakdown against the 4-hour budget.
- **Use of AI coding assistants**: this session used Claude Code for design and implementation, per the brief's §5.3 requirement to disclose it.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: complete README with setup, run time, extensibility, and private dataset notes"
```

---

## Task 12: Write `DESIGN_NOTE.md`

**Files:**
- Modify: `DESIGN_NOTE.md`

- [ ] **Step 1: Write ~1000 words covering the three required sections**

Fill in `DESIGN_NOTE.md`'s three sections per `BRIEF.md` §6.1 and spec §1:
1. **Approach and alternatives** — for entity detection/resolution, relation extraction, and observation extraction: what was built (spec §4–§6) and the alternatives considered (local NER/LLM model, dependency-parse relation extraction — spec §4/§6), plus what would change with a frontier LLM endpoint (e.g. zero-shot entity/relation extraction with structured output, LLM-as-resolver for ambiguous aliases).
2. **Evaluation** — no labels are provided (brief §6.1.2): propose a small hand-labeled sample (e.g. 20–30 emails double-annotated for entities/relations) to compute precision/recall for resolution and relation/observation extraction; propose reference-list coverage metrics (% of gazetteer entities ever matched) and new-entity-rate monitoring as an unsupervised proxy for drift on the private dataset; propose spot-checking observation timelines against known ground truth in a couple of manually traced incidents.
3. **Trade-offs and next steps** — limitations of the rule-based approach (recall on paraphrased text, brittle regex fallback, no coreference across pronouns), and what more time would buy (coreference resolution, a small trained classifier for relation typing, active-learning loop from the evaluation sample).

- [ ] **Step 2: Commit**

```bash
git add DESIGN_NOTE.md
git commit -m "docs: write design note covering approach, evaluation, and trade-offs"
```

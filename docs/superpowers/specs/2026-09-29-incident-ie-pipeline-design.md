# Incident email IE pipeline — design spec

Date: 2026-09-29
Status: approved (chat approval 2026-09-29)

## 1. Purpose and constraints

Build a pipeline that reads `.eml` incident emails, extracts mentions of four
entity types, resolves each mention to one entity, links entities with
relation types, records dated observations with source email provenance, and
writes a small queryable database. Full requirements: `BRIEF.md`.

Hard constraints carried into every design choice below:
- No hosted LLM / external API at run time; CPU-only local processing.
- Full run on ~270 emails must fit in ~10 minutes on a small machine.
- Must run unmodified on a private dataset with the same `.eml` format and
  reference CSV columns, but different region/entities/IDs — nothing may be
  hardcoded to this scenario's names or IDs.
- At least one stage must be extensible without a rewrite.
- CLI: `python -m pipeline --emails <folder> --reference <folder> --out <folder>`.

## 2. Data shape (confirmed by inspection)

- 271 `.eml` files. 263 `text/plain`, 6 `multipart/alternative` (plain +
  html), 2 `text/html`-only. All parseable via stdlib `email` (handles
  quoted-printable transfer encoding automatically via `get_content()`).
- Reference CSVs: `lrfs.csv` (39 rows), `incidents.csv` (27), `organisations.csv`
  (118), `sites.csv` (131). Columns per `data/README.md`; `aliases` is
  `|`-separated.
- Some emails are free text; some are structured "sitrep" style with
  per-incident headers (`A. Storm Fenella`, `Status: ...`, `Lead: ...`) — a
  useful high-precision signal for observations where present, but the
  pipeline must not depend on this structure existing.

## 3. Architecture

```
pipeline/
  __main__.py        CLI entry point (argparse), orchestrates the stages below
  emails.py           .eml -> plain-text body + headers (From, Date, Message-ID, Subject)
  reference.py         load reference CSVs into per-type gazetteers (name+aliases -> id)
  extract.py           find candidate entity mentions in email text (gazetteer + regex fallback)
  resolve.py            mention -> entity id (exact/alias match, fuzzy match, or new entity)
  relations.py          co-occurrence + cue-keyword relation extraction (rules externalized)
  observations.py       property/state extraction per entity type, tied to email date + source
  rules/relations.yaml  extensible cue-keyword table (relation type -> trigger phrases)
  rules/observations.yaml state keywords per entity type/property
  store.py              write SQLite db + CSV table dumps to --out
```

Pipeline flow per email: parse -> detect mentions -> resolve to entity IDs ->
extract relations among resolved entities co-occurring in the same window ->
extract observations for resolved entities -> accumulate; after all emails,
write entities/relations/observations to `--out`.

Entity resolution happens before and independently of relation/observation
extraction; relation/observation steps only ever operate on already-resolved
entity IDs (per BRIEF.md §2.1: "linking does not replace entity resolution").

## 4. Entity mention detection & resolution

1. Build a gazetteer per entity type from the matching reference CSV: every
   `name` and each `|`-split alias, lowercased, mapped to its reference ID.
   This is read from `--reference` at run time, so it works unmodified on the
   private dataset's own reference lists.
2. Scan each email's plain-text body for gazetteer matches (case-insensitive
   substring/phrase match over tokenized text, longest-match-first to avoid
   partial overlaps, e.g. "Cumbria Resilience Forum" before "Cumbria").
3. For text spans not matched to a gazetteer entry, apply per-type regex/
   heuristic fallbacks to catch entities absent from the reference list
   (e.g. road patterns `\bA\d{2,4}\b`, capitalized multi-word phrases next to
   type cue words like "rest centre", "treatment works", "primary school").
   Matches here become **new** entities with freshly minted IDs
   (`SITE-NEW-###` etc.), not reference IDs.
4. Fuzzy matching (`rapidfuzz.fuzz.token_sort_ratio`, threshold ~90) is
   applied when no exact/alias match is found, against both the reference
   gazetteer and entities already newly created in this run, before minting
   a new entity — this avoids duplicate new entities for minor name variants
   across emails (e.g. "Penrith rest centre" vs "the Penrith Rest Centre").
5. Every mention keeps a link to its source email and matched surface text,
   even after resolution, so provenance is auditable.

## 5. Relations

Rule-based co-occurrence: within an email, pairs of resolved entities whose
mentions fall in the same paragraph (or a fixed-size sentence window) are
candidate relations. A cue-keyword table in `rules/relations.yaml` maps
trigger phrases near the pair to a relation type:

```yaml
AFFECTS:        [flooded, flooding, closed, closure, disruption, affected, damaged]
COORDINATED_BY: [coordinated by, chaired by, led by, multi-agency]
RESPONDS_TO:    [responding to, attended, deployed to, supporting the response]
OPERATES:       [operates, runs, manages, responsible for]
```

The (from-type, to-type) pairing for each relation constrains which
candidate pairs are considered (e.g. `AFFECTS` only between incident and
site). Adding a relation type is a YAML edit plus one line registering its
entity-type pair — no code change — this is the pipeline's designated
extensible stage per BRIEF.md §1.

## 6. Observations

For each resolved entity, `rules/observations.yaml` defines keyword ->
property/value mappings per entity type (e.g. incident: "stood down" ->
`status=closed`; site: "reopened" -> `status=open`, "flooded" -> `status=affected`).
Every match produces one observation row:

`(entity_id, property, value, observed_at, source_email, snippet)`

`observed_at` is the email's `Date` header (parsed to UTC). `source_email`
is the file path + `Message-ID`. No overwriting or dedup — every report is
kept, so later corrections and reversals (a road that closes then reopens)
are visible as separate rows, letting the store answer "what did we believe
about X as of date Y" and "how has X changed."

## 7. Storage

SQLite database at `<out>/pipeline.db` (stdlib `sqlite3`, no dependency):

- `entities(id, type, canonical_name, is_new, first_seen_email, created_at)`
- `entity_aliases(entity_id, alias_text, source_email)` — every surface form
  seen, for auditability and debugging resolution quality.
- `relations(id, relation_type, from_entity_id, to_entity_id, source_email, observed_at)`
- `observations(id, entity_id, property, value, observed_at, source_email, snippet)`
- `source_emails(message_id, path, from_addr, date, subject)`

The same tables are also dumped as CSV under `<out>/csv/` for easy diffing
and inspection without a SQLite client.

## 8. Stack / dependencies

Stdlib (`email`, `sqlite3`, `argparse`, `csv`, `re`, `html.parser` for
stripping the rare HTML-only bodies) plus one runtime dependency,
`rapidfuzz`, for fuzzy matching. No spaCy, no local LLM — see design note for
the reasoning (reliability/runtime/robustness on an unseen private dataset
over recall).

## 9. Testing approach

Unit tests (pytest) for the parts with real logic and clear inputs/outputs:
- `emails.py`: parsing plain/multipart/HTML `.eml` fixtures into clean text + headers.
- `reference.py`: gazetteer building from CSV including alias splitting.
- `resolve.py`: exact, alias, fuzzy, and new-entity-creation cases, including
  dedup of repeated new entities across two mentions.
- `relations.py`: cue-keyword -> relation type mapping, entity-type-pair
  filtering.
- `observations.py`: keyword -> property/value mapping.
No golden end-to-end labels exist, so a small hand-picked set of 3-5 emails
gets an eyeballed expected-output fixture for a smoke-level integration test;
broader evaluation strategy (no labels available) is covered in
`DESIGN_NOTE.md`.

## 10. Private dataset fit (preview of README §4 table)

Gazetteer-based resolution and relation/observation rule tables are all
driven by files read at run time (`--reference`, `rules/*.yaml`), not
hardcoded scenario values, so they carry over directly. The regex-based new-
entity fallback (road patterns, "rest centre" etc.) is UK-incident-generic
rather than scenario-specific, so it should also transfer, with lower
confidence than gazetteer matches. This gets written up properly in the
README's private-dataset table once the pipeline is built.

## 11. Explicit scope cuts (given the 4-hour budget)

- No local NER/LLM model — pure rule-based, per §4/§8.
- No cross-email entity merge beyond exact/alias/fuzzy matching (no
  clustering algorithm).
- No web UI; SQLite + CSV output only, queried via `sqlite3` CLI or pandas.
- Relation/observation windowing is paragraph-based, not full coreference
  resolution.

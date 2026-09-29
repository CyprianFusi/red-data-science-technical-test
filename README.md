# Incident Email IE Pipeline

An information-extraction pipeline that reads incident-response `.eml` emails, resolves mentions of four entity types (LRF, incident, organisation, site) against reference lists, links them with relation types, and records every reported fact as a dated, source-attributed observation in a small SQLite database.

## Setup

Requires Python 3.13 and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
```

This installs the three runtime/dev dependencies declared in `pyproject.toml`: `rapidfuzz` (fuzzy string matching for entity resolution), `pyyaml` (loading the relation/observation rule tables), and `pytest` (test suite). No network access is required after this step — the pipeline itself never calls a hosted LLM or external API.

## Run

```bash
python -m pipeline --emails data/emails --reference data/reference --out output
```

- `--emails` — folder of `.eml` files.
- `--reference` — folder containing `lrfs.csv`, `incidents.csv`, `organisations.csv`, `sites.csv` (same column layout as `data/README.md` describes).
- `--out` — output folder; created if it doesn't exist.

To run against the private dataset, point `--emails` and `--reference` at its folders — the command is otherwise identical:

```bash
python -m pipeline --emails /path/to/private/emails --reference /path/to/private/reference --out output
```

Output: `output/pipeline.db` (SQLite, tables `source_emails`, `entities`, `entity_aliases`, `relations`, `observations`) plus the same five tables dumped as CSV under `output/csv/` for quick inspection without a SQLite client.

Run the test suite with:

```bash
uv run pytest
```

## Run time

Measured on the provided dataset (271 emails, Windows 11, Python 3.13.9, no GPU — pure-CPU rule-based processing):

```
Processed 271 emails -> 85 entities, 1725 relations, 660 observations. Output: output
real    0m2.0s
```

~2 seconds, well inside the 10-minute budget. The approach is linear in the number of emails and does no model inference, so the private dataset (similar email count) should run in a comparable time.

## Extending the pipeline

The relation and observation extraction rules are the designated extensible stage — both are plain YAML files read at run time, not hardcoded in Python:

- **Add a relation type**: add an entry to `pipeline/rules/relations.yaml` (relation name -> list of cue keywords/phrases), then add one line to `RELATION_ENTITY_TYPES` in `pipeline/relations.py` declaring which `(from_entity_type, to_entity_type)` pair it applies to. No other code change is needed.
- **Add or tune an observation rule**: add a `[keyword, property, value]` triple under the relevant entity type in `pipeline/rules/observations.yaml`. No code change at all.
- **Add a new entity type**: would need a new reference CSV convention (id/name/aliases columns), an entry in `REFERENCE_FILES`/`ID_COLUMNS` in `pipeline/reference.py`, and optionally a fallback regex pattern in `pipeline/extract.py`'s `FALLBACK_PATTERNS`. Everything downstream (resolution, relations, observations, storage) is already generic over entity type.

## Private dataset

| Stage / component | Will it work on the private dataset? | Why |
|---|---|---|
| Email parsing (`pipeline/emails.py`) | Yes | Uses Python's stdlib `email` parser against the MIME structure, not this scenario's content. Handles plain text, multipart/alternative, and HTML-only bodies. |
| Reference loading (`pipeline/reference.py`) | Yes | Reads whichever CSVs are passed via `--reference`; column names are fixed by the brief, not by this scenario's row values. |
| Gazetteer entity resolution (exact/alias/fuzzy match) | Yes | Entirely driven by the reference CSVs read at run time — no entity names or IDs from this scenario are hardcoded anywhere in `pipeline/` (checked by `tests/test_pipeline_integration.py::test_pipeline_source_has_no_hardcoded_scenario_names`, which scans the source against `data/reference/*.csv`). |
| New-entity regex fallback (`FALLBACK_PATTERNS` in `pipeline/extract.py`) | Partly | Patterns key on generic UK-incident vocabulary (road-number format `A\d+`, "...Council", "...Local Resilience Forum", "Storm <Name>", "...Rest Centre"/"...Treatment Works" etc.), not this scenario's specific names, so they should still fire on a different region. Precision will likely be lower than the gazetteer path since these are heuristics, not exact matches — expect more borderline/incorrect new entities than on the provided dataset. |
| Relation cue-keyword table (`pipeline/rules/relations.yaml`) | Yes, with caveats | Keywords are generic incident-response vocabulary ("closed", "flooded", "Lead:", "run by", "RESPONDING", etc.), not scenario-specific names, so they should transfer. Coverage was tuned against this dataset's phrasing (see "Assumptions" below); a private dataset with different sitrep conventions may need the keyword list extended the same way — this is a YAML edit, not code. |
| Observation keyword table (`pipeline/rules/observations.yaml`) | Yes, with caveats | Same reasoning as relations: generic status vocabulary, same caveat about dataset-specific phrasing needing keyword additions over time. |
| Co-occurrence relation/observation windowing | Yes | Window size is a fixed character count, not tied to this scenario's text. |
| Storage (`pipeline/store.py`) | Yes | Schema and CSV export are entity-type-agnostic. |

Nothing in `pipeline/` hardcodes this scenario's entity names, IDs, or region — everything scenario-specific lives in `data/` and is passed via `--emails`/`--reference`, which is exactly what changes for the private dataset.

## Assumptions

Where the brief left a design choice open, these are the choices made (see `DESIGN_NOTE.md` for the fuller reasoning):

- **Relation/observation "co-occurrence" is windowed by character count**, not by sentence or paragraph boundaries: relations use a 400-character window around a candidate entity pair, observations use a 120-character window around a single mention. This is simple and fast but can produce false positives when an email densely lists several sites/organisations close together (see `DESIGN_NOTE.md` for the trade-off).
- **Fuzzy-match threshold is 90** (out of 100, `rapidfuzz.fuzz.token_sort_ratio`) for both matching an unresolved mention against the reference gazetteer and deduplicating repeated new entities. Chosen to tolerate minor typos/wording variants while avoiding false merges of distinct entities.
- **New entity IDs** are minted as `<TYPE>-NEW-<counter>` (e.g. `SITE-NEW-001`), scoped per pipeline run — they are not stable across separate runs of the pipeline on the same data, since there is no cross-run identity store. Re-running produces the same *set* of new entities but not guaranteed identical IDs run-to-run relative to any external system.
- **Relation and observation cue keywords started from a generic guess and were corrected against the real dataset** during implementation (see `DESIGN_NOTE.md` §3): an initial pass produced zero `COORDINATED_BY`/`RESPONDS_TO`/`OPERATES` relations; inspecting the actual emails showed the dataset consistently uses "Lead:", "RESPONDING", and "run by" rather than the words first guessed. The keyword tables were expanded accordingly. This is disclosed rather than hidden because it is exactly the kind of dataset-specific tuning a private dataset may also need — see the Private Dataset table above.
- **Entities are only recorded in the output if they are actually mentioned** in at least one email — the full reference lists are not dumped verbatim into `entities`, only the subset that appears in the data.

## How I used my time

Roughly 4 hours, in this order:

1. Reading the brief, inspecting the data, and confirming the CLI contract (~15 min).
2. Design: architecture, entity resolution approach, storage format, deciding against a local NER/LLM model in favour of gazetteer + rules given the 10-minute/CPU-only/no-network constraints (~20 min).
3. Implementation, test-first, module by module: text utils, email parsing, reference loading, mention detection, entity resolution, relation extraction, observation extraction, SQLite/CSV storage, CLI wiring (~2.5 hours).
4. Running on the real dataset, investigating why three of the four relation types never fired, and expanding the cue-keyword YAML accordingly (~20 min).
5. Addressing a CSV formula-injection finding in the CSV export path (~10 min).
6. Writing this README and `DESIGN_NOTE.md` (~25 min).

Not finished / would do with more time: a labelled evaluation sample (see `DESIGN_NOTE.md` §2), coreference resolution across pronouns/implicit references, and tightening the co-occurrence window to reduce over-triggering of `OPERATES` in dense sitrep emails (see `DESIGN_NOTE.md` §3).

## Use of AI coding assistants

This entire pipeline was designed and implemented with Claude Code (Anthropic's CLI coding agent) in an interactive session: brainstorming the architecture, writing the design spec and implementation plan, and implementing every module test-first, task by task, with the emails/reference data inspected directly at each design decision point. All code was written by the assistant under direct human review and direction at each stage (design approval, plan approval, and step-by-step execution); no code in `pipeline/` calls a hosted LLM or external API at run time — the assistant was used only during development, per §5.3 of the brief.

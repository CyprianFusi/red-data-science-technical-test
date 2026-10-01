# Incident Email IE Pipeline

An information-extraction pipeline that reads incident-response `.eml` emails, resolves mentions of four entity types (LRF, incident, organisation, site) against reference lists, links them with relation types, and records every reported fact as a dated, source-attributed observation in a small SQLite database.

## Screenshots

### Observations table
![Observations-table](https://raw.githubusercontent.com/CyprianFusi/red-data-science-technical-test/main/assets/ui_1.png)

## Setup

Requires Python 3.13 and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
```

This installs the three runtime/dev dependencies declared in `pyproject.toml`: `rapidfuzz` (fuzzy string matching for entity resolution), `pyyaml` (loading the relation/observation rule tables), and `pytest` (test suite), into a `.venv` managed by `uv`. No network access is required after this step — the pipeline itself never calls a hosted LLM or external API.

The brief's contract command is `python -m pipeline ...` with no `uv run` prefix, so before running it, activate that environment once per shell session — `source .venv/bin/activate` (macOS/Linux) or `.venv\Scripts\activate` (Windows) — or prefix every command below with `uv run`. Without one of those, a bare `python` resolves to the system interpreter, which doesn't have `rapidfuzz`/`pyyaml` installed.

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
Processed 271 emails -> 76 entities, 145 relations, 224 observations. Output: output
real    0m2.2s
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
| Co-occurrence relation/observation windowing | Yes | Window size is a fixed character count clamped to the mention's own line/bullet (and, for relations, blocked from crossing a bulleted/numbered list boundary) — none of that logic is tied to this scenario's text. |
| Storage (`pipeline/store.py`) | Yes | Schema and CSV export are entity-type-agnostic. |

Nothing in `pipeline/` hardcodes this scenario's entity names, IDs, or region — everything scenario-specific lives in `data/` and is passed via `--emails`/`--reference`, which is exactly what changes for the private dataset.

## Assumptions

Where the brief left a design choice open, these are the choices made (see `DESIGN_NOTE.md` for the fuller reasoning):

- **Relation/observation "co-occurrence" is windowed by character count, clamped to a line/bullet**, not by full sentence or paragraph boundaries: relations use a 400-character gate around a candidate entity pair and are additionally blocked from crossing a bulleted/numbered list-item boundary (fixing an early over-triggering bug — see `DESIGN_NOTE.md`); observations use a 120-character window clamped to the mention's own line. Two facts on the *same* line about *different* entities (e.g. an email subject "Cockermouth School closed and A591 reopened") can still both attach to whichever entity is nearest — a known residual limitation, not a bug, and a minority case in practice (5 same-email status conflicts remained on the provided dataset, down from 103 before this fix).
- **Fuzzy-match threshold is 90** (out of 100, `rapidfuzz.fuzz.token_sort_ratio`) for both matching an unresolved mention against the reference gazetteer and deduplicating repeated new entities. Chosen to tolerate minor typos/wording variants while avoiding false merges of distinct entities.
- **New entity IDs** are minted as `<TYPE>-NEW-<counter>` (e.g. `SITE-NEW-001`), scoped per pipeline run — they are not stable across separate runs of the pipeline on the same data, since there is no cross-run identity store. Re-running produces the same *set* of new entities but not guaranteed identical IDs run-to-run relative to any external system.
- **Relation and observation cue keywords started from a generic guess and were corrected against the real dataset** during implementation (see `DESIGN_NOTE.md` §3): an initial pass produced zero `COORDINATED_BY`/`RESPONDS_TO`/`OPERATES` relations; inspecting the actual emails showed the dataset consistently uses "Lead:", "RESPONDING", and "run by" rather than the words first guessed. The keyword tables were expanded accordingly. This is disclosed rather than hidden because it is exactly the kind of dataset-specific tuning a private dataset may also need — see the Private Dataset table above.
- **Entities are only recorded in the output if they are actually mentioned** in at least one email — the full reference lists are not dumped verbatim into `entities`, only the subset that appears in the data.

## How I used my time

Roughly 4 hours of design/implementation as originally scoped, plus a further review-and-fix pass (see below) that materially improved output quality:

1. Reading the brief, inspecting the data, and confirming the CLI contract (~15 min).
2. Design: architecture, entity resolution approach, storage format, deciding against a local NER/LLM model in favour of gazetteer + rules given the 10-minute/CPU-only/no-network constraints (~20 min).
3. Implementation, test-first, module by module: text utils, email parsing, reference loading, mention detection, entity resolution, relation extraction, observation extraction, SQLite/CSV storage, CLI wiring (~2.5 hours).
4. Running on the real dataset, investigating why three of the four relation types never fired, and expanding the cue-keyword YAML accordingly (~20 min).
5. Addressing a CSV formula-injection finding in the CSV export path (~10 min).
6. Writing this README and `DESIGN_NOTE.md` (~25 min).
7. A fresh-context code review of the whole branch, then a fix pass for everything it found at Critical/Important severity (a newline bug that let fallback regexes absorb email signature blocks into entity names; a missing/duplicate Message-ID crash; relation/observation windows bleeding across sitrep bullets and producing 1511 near-duplicate `OPERATES` relations from one keyword; quoted reply text being re-timestamped; one malformed email aborting the whole run; a duplicate reference name resolved by silent CSV row order; a gazetteer match-boundary bug; non-UTC dates not normalized) — each fixed test-first and re-verified against the real dataset.

Not finished / would do with more time: a labelled evaluation sample (see `DESIGN_NOTE.md` §2), coreference resolution across pronouns/implicit references, and clause-level (not just line-level) splitting for the residual same-line-different-entity ambiguity noted in Assumptions above.

## Use of AI coding assistants

This entire pipeline was designed and implemented with Claude Code (Anthropic's CLI coding agent) in an interactive session: brainstorming the architecture, writing the design spec and implementation plan, and implementing every module test-first, task by task, with the emails/reference data inspected directly at each design decision point. After the initial implementation, a fresh-context review pass (a separate Claude Code review agent, prompted to independently re-derive findings from the code and the real dataset rather than trust the implementation's own account) found the eight issues fixed in "How I used my time" step 7 above — it was given the chance to push back on prior design decisions and did (e.g. disagreeing with how a prior relation-keyword fix traded a recall problem for a precision one), which fed directly into the fix pass. All code was written by the assistant under direct human review and direction at each stage (design approval, plan approval, step-by-step execution, and review triage); no code in `pipeline/` calls a hosted LLM or external API at run time — the assistant was used only during development, per §5.3 of the brief.

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

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

        # Don't let the window cross into a neighbouring line: sitrep-style
        # emails list one entity's status per line/bullet, and a raw
        # character window bleeds a neighbour's keyword onto this entity.
        line_start = text.rfind("\n", 0, mention.start) + 1
        line_end = text.find("\n", mention.end)
        if line_end == -1:
            line_end = len(text)
        lo = max(lo, line_start)
        hi = min(hi, line_end)

        window = text[lo:hi]
        window_lower = window.lower()

        for keyword, prop, value in entity_rules:
            if keyword.lower() in window_lower:
                observations.append(
                    Observation(entity, prop, value, observed_at, source_email, window.strip())
                )

    return observations

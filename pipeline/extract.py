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
            r"\b[A-Z][a-zA-Z'-]*(?:[ \t]+[A-Z][a-zA-Z'-]*){0,3}[ \t]+"
            r"(?:Rest Centre|Treatment Works|Primary School|Leisure Centre|Bridge)\b"
        ),
    ],
    "organisation": [
        re.compile(
            r"\b[A-Z][a-zA-Z'&-]*(?:[ \t]+[A-Z][a-zA-Z'&-]*){0,3}[ \t]+"
            r"(?:Council|Police|Fire and Rescue Service|NHS Trust|Water)\b"
        ),
    ],
    "incident": [
        re.compile(r"\bStorm[ \t]+[A-Z][a-z]+\b"),
    ],
    "lrf": [
        re.compile(
            r"\b[A-Z][a-zA-Z'-]*(?:[ \t]+[A-Z][a-zA-Z'-]*){0,4}[ \t]+"
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
            pattern = re.compile(r"(?<!\w)" + re.escape(key) + r"(?!\w)", re.IGNORECASE)
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

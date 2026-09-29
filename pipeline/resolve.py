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

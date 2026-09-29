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

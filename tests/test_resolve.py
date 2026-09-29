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
    "site": _gaz("site", [("SITE-0001", "A591 Keswick to Grasmere", ["A591"])]),
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

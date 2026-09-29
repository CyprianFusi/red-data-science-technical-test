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

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


def test_relation_does_not_cross_a_bulleted_list_item_boundary():
    """Regression: a sitrep listing several sites, each with its own
    "(run by X)" bullet, must not link a site to an organisation that
    "run by" happens to be near for someone else's bullet."""
    text = (
        "- Castle Park bottled water station: open (run by UU)\n"
        "- Eamont Moor: offline (run by United Utilities)\n"
    )
    site1_name = "Castle Park bottled water station"
    org_name = "United Utilities"
    site1_start = text.index(site1_name)
    org_start = text.index(org_name)

    site1 = ResolvedEntity("SITE-0001", "site", site1_name, is_new=False)
    org = ResolvedEntity("ORG-001", "organisation", org_name, is_new=False)

    mentions = [
        (Mention("site", site1_name, site1_start, site1_start + len(site1_name), "SITE-0001"), site1),
        (Mention("organisation", org_name, org_start, org_start + len(org_name), "ORG-001"), org),
    ]
    rules = {**RULES, "OPERATES": ["run by"]}
    relations = extract_relations(text, mentions, rules, "email-1.eml", None)
    assert relations == []


def test_relation_still_found_within_a_single_bullet():
    text = "- Eamont Moor: offline (run by United Utilities)\n"
    site_name = "Eamont Moor"
    org_name = "United Utilities"
    site_start = text.index(site_name)
    org_start = text.index(org_name)

    site = ResolvedEntity("SITE-0002", "site", site_name, is_new=False)
    org = ResolvedEntity("ORG-001", "organisation", org_name, is_new=False)

    mentions = [
        (Mention("site", site_name, site_start, site_start + len(site_name), "SITE-0002"), site),
        (Mention("organisation", org_name, org_start, org_start + len(org_name), "ORG-001"), org),
    ]
    rules = {**RULES, "OPERATES": ["run by"]}
    relations = extract_relations(text, mentions, rules, "email-1.eml", None)
    assert len(relations) == 1
    assert relations[0].relation_type == "OPERATES"
    assert relations[0].from_entity.entity_id == "ORG-001"
    assert relations[0].to_entity.entity_id == "SITE-0002"


def test_extract_relations_dedups_repeated_pair_in_same_email():
    text = "Storm Fenella has closed the A591. The A591 was closed by Storm Fenella again."
    mention_a1 = Mention("incident", "Storm Fenella", 0, 13, "INC-001")
    mention_b1 = Mention("site", "A591", 26, 30, "SITE-0001")
    mention_b2 = Mention("site", "A591", 40, 44, "SITE-0001")
    mention_a2 = Mention("incident", "Storm Fenella", 60, 73, "INC-001")
    mentions = [
        (mention_a1, INCIDENT),
        (mention_b1, SITE),
        (mention_b2, SITE),
        (mention_a2, INCIDENT),
    ]
    relations = extract_relations(text, mentions, RULES, "email-1.eml", None)
    assert len(relations) == 1


def test_load_relation_rules_reads_yaml(tmp_path):
    rules_file = tmp_path / "relations.yaml"
    rules_file.write_text("AFFECTS:\n  - closed\n  - flooded\n")
    rules = load_relation_rules(rules_file)
    assert rules == {"AFFECTS": ["closed", "flooded"]}

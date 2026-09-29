from datetime import datetime, timezone

from pipeline.extract import Mention
from pipeline.observations import extract_observations, load_observation_rules
from pipeline.resolve import ResolvedEntity

RULES = {
    "site": [("closed", "status", "closed"), ("reopened", "status", "open")],
    "incident": [("stood down", "status", "closed")],
}

SITE = ResolvedEntity("SITE-0001", "site", "A591", is_new=False)
INCIDENT = ResolvedEntity("INC-001", "incident", "Storm Fenella", is_new=False)


def test_extracts_observation_for_keyword_near_mention():
    text = "The A591 is closed between Keswick and Grasmere."
    mentions = [(Mention("site", "A591", 4, 8, "SITE-0001"), SITE)]
    observations = extract_observations(text, mentions, RULES, "email-1.eml", None)
    assert len(observations) == 1
    assert observations[0].property == "status"
    assert observations[0].value == "closed"
    assert observations[0].entity.entity_id == "SITE-0001"


def test_no_observation_when_keyword_far_from_mention():
    text = "A591. " + ("padding " * 40) + "The road was later reopened."
    mentions = [(Mention("site", "A591", 0, 4, "SITE-0001"), SITE)]
    observations = extract_observations(text, mentions, RULES, "email-1.eml", None, window_chars=30)
    assert observations == []


def test_multiple_entities_each_get_own_observation():
    text = "The A591 is closed. Storm Fenella has been stood down."
    mentions = [
        (Mention("site", "A591", 4, 8, "SITE-0001"), SITE),
        (Mention("incident", "Storm Fenella", 21, 34, "INC-001"), INCIDENT),
    ]
    observations = extract_observations(text, mentions, RULES, "email-1.eml", None)
    values = {(o.entity.entity_id, o.property, o.value) for o in observations}
    assert ("SITE-0001", "status", "closed") in values
    assert ("INC-001", "status", "closed") in values


def test_observation_carries_observed_at_and_source_email():
    when = datetime(2026, 1, 15, tzinfo=timezone.utc)
    text = "The A591 is closed."
    mentions = [(Mention("site", "A591", 4, 8, "SITE-0001"), SITE)]
    observations = extract_observations(text, mentions, RULES, "email-1.eml", when)
    assert observations[0].observed_at == when
    assert observations[0].source_email == "email-1.eml"


def test_load_observation_rules_reads_yaml(tmp_path):
    rules_file = tmp_path / "observations.yaml"
    rules_file.write_text("site:\n  - [closed, status, closed]\n")
    rules = load_observation_rules(rules_file)
    assert rules == {"site": [("closed", "status", "closed")]}

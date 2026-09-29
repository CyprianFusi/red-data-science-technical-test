from pathlib import Path

from pipeline.reference import load_all_gazetteers, load_gazetteer

FIXTURES = Path(__file__).parent / "fixtures" / "reference"


def test_load_gazetteer_indexes_name_and_aliases():
    gaz = load_gazetteer(FIXTURES, "lrf")
    assert gaz.entity_type == "lrf"
    assert gaz.lookup["cumbria local resilience forum"] == "LRF-01"
    assert gaz.lookup["cumbria lrf"] == "LRF-01"
    assert gaz.lookup["cumbria resilience forum"] == "LRF-01"
    assert gaz.entities_by_id["LRF-01"].name == "Cumbria Local Resilience Forum"
    assert gaz.entities_by_id["LRF-01"].aliases == ("Cumbria LRF", "Cumbria Resilience Forum")


def test_load_gazetteer_handles_empty_aliases_column():
    gaz = load_gazetteer(FIXTURES, "incident")
    assert gaz.entities_by_id["INC-001"].aliases == ()
    assert gaz.lookup["storm fenella"] == "INC-001"


def test_load_all_gazetteers_returns_all_four_types():
    gazetteers = load_all_gazetteers(FIXTURES)
    assert set(gazetteers) == {"lrf", "incident", "organisation", "site"}
    assert gazetteers["site"].lookup["a591"] == "SITE-0001"

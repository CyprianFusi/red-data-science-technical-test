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


def test_duplicate_name_across_rows_resolves_deterministically_to_first_row(tmp_path):
    """Two distinct sites can legitimately share a name (e.g. "Riverside
    Community Centre" in two different towns). Silently letting whichever
    CSV row happens to load last win is an accident of file order, not a
    decision — the first row must always win, and the collision must be
    visible rather than invisible."""
    csv_path = tmp_path / "sites.csv"
    csv_path.write_text(
        "site_id,name,aliases,site_type,locality\n"
        "SITE-A,Riverside Community Centre,,site,Carlisle\n"
        "SITE-B,Riverside Community Centre,,site,Kendal\n"
    )
    gaz = load_gazetteer(tmp_path, "site")
    assert gaz.lookup["riverside community centre"] == "SITE-A"
    assert "riverside community centre" in gaz.ambiguous_keys

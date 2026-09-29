from pipeline.textutils import normalize_text


def test_normalize_lowercases_and_strips():
    assert normalize_text("  Cumbria Resilience Forum  ") == "cumbria resilience forum"


def test_normalize_collapses_internal_whitespace():
    assert normalize_text("A591   Keswick\tto Grasmere") == "a591 keswick to grasmere"


def test_normalize_empty_string():
    assert normalize_text("") == ""

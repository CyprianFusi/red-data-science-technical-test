"""Shared text normalization used by gazetteer matching and resolution."""
import re

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.strip().lower())

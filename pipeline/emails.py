"""Parse .eml files into plain text + headers for downstream extraction."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path


@dataclass
class ParsedEmail:
    path: Path
    message_id: str
    from_addr: str
    date: datetime | None
    subject: str
    text: str


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def get_text(self) -> str:
        return " ".join(chunk.strip() for chunk in self._chunks if chunk.strip())


def _html_to_text(html: str) -> str:
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


def parse_eml(path: Path) -> ParsedEmail:
    with open(path, "rb") as fh:
        msg = BytesParser(policy=policy.default).parse(fh)

    body_part = msg.get_body(preferencelist=("plain", "html"))
    if body_part is None:
        text = ""
    else:
        content = body_part.get_content()
        text = _html_to_text(content) if body_part.get_content_type() == "text/html" else content

    date_header = msg.get("Date")
    date: datetime | None
    try:
        date = parsedate_to_datetime(date_header) if date_header else None
    except (TypeError, ValueError):
        date = None

    return ParsedEmail(
        path=path,
        message_id=(msg.get("Message-ID") or "").strip("<>"),
        from_addr=msg.get("From") or "",
        date=date,
        subject=msg.get("Subject") or "",
        text=text.strip(),
    )


def parse_eml_folder(folder: Path) -> list[ParsedEmail]:
    paths = sorted(folder.glob("*.eml"), key=lambda p: p.name)
    return [parse_eml(p) for p in paths]

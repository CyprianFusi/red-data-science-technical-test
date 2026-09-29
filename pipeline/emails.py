"""Parse .eml files into plain text + headers for downstream extraction."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
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


def _strip_quoted_lines(text: str) -> str:
    # A line quoted from an earlier message in a reply chain ("> ...",
    # possibly nested ">> ...") reports a status as of that earlier
    # message's date, not this email's Date header — extracting it here
    # would attribute a stale report to a later timestamp.
    return "\n".join(
        line for line in text.split("\n") if not line.lstrip().startswith(">")
    )


def parse_eml(path: Path) -> ParsedEmail:
    with open(path, "rb") as fh:
        msg = BytesParser(policy=policy.default).parse(fh)

    body_part = msg.get_body(preferencelist=("plain", "html"))
    if body_part is None:
        text = ""
    else:
        try:
            content = body_part.get_content()
        except (LookupError, UnicodeDecodeError):
            # An unrecognized/garbled charset declaration must not abort
            # the whole run over one email — fall back to a lossy decode
            # of the raw payload instead of raising.
            raw = body_part.get_payload(decode=True) or b""
            content = raw.decode("utf-8", errors="replace")
        text = _html_to_text(content) if body_part.get_content_type() == "text/html" else content
        text = _strip_quoted_lines(text)

    date_header = msg.get("Date")
    date: datetime | None
    try:
        date = parsedate_to_datetime(date_header) if date_header else None
    except (TypeError, ValueError):
        date = None
    if date is not None:
        # Normalize to UTC: observations are ordered with a lexicographic
        # string comparison on the stored ISO timestamp, which only sorts
        # correctly across emails if every timestamp uses the same offset.
        date = date.astimezone(timezone.utc) if date.tzinfo else date.replace(tzinfo=timezone.utc)

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
    parsed: list[ParsedEmail] = []
    for path in paths:
        try:
            parsed.append(parse_eml(path))
        except Exception as exc:  # noqa: BLE001 - one bad file must not abort the run
            print(f"warning: skipping unparseable email {path}: {exc}", file=sys.stderr)
    return parsed

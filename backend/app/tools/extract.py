"""Text extraction from fetched or uploaded documents. All content is untrusted data:
nothing is executed, scripts and styles are dropped, and text is only ever stored and quoted."""

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from html.parser import HTMLParser

from app.config import BACKEND_DIR

MAX_PDF_PAGES = 200
PDF_TIMEOUT_SECONDS = 20.0
MIN_CHARS_PER_PAGE = 20

_SKIP_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "iframe",
        "object",
        "embed",
        "canvas",
        "head",
        "nav",
        "footer",
        "form",
        "button",
        "select",
    }
)
_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "main",
        "header",
        "li",
        "ul",
        "ol",
        "table",
        "tr",
        "td",
        "th",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "pre",
        "blockquote",
        "br",
        "hr",
        "dd",
        "dt",
        "figcaption",
    }
)


class ExtractionError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Segment:
    locator: str | None
    text: str


@dataclass(frozen=True)
class ExtractedDocument:
    title: str | None
    segments: list[Segment]
    pages: int | None = None

    @property
    def text(self) -> str:
        return "\n\n".join(s.text for s in self.segments)


class _HtmlText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        elif not self._skip_depth:
            self.parts.append(data)


def _normalize(text: str) -> str:
    paragraphs = (re.sub(r"[ \t\r\f\v\n]+", " ", p).strip() for p in re.split(r"\n\s*\n", text))
    return "\n\n".join(p for p in paragraphs if p)


def decode(body: bytes, charset: str | None) -> str:
    try:
        return body.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def extract_html(html: str) -> ExtractedDocument:
    parser = _HtmlText()
    parser.feed(html)
    parser.close()
    title = _normalize("".join(parser.title_parts))[:500] or None
    text = _normalize("".join(parser.parts))
    if not text:
        raise ExtractionError("no_text")
    return ExtractedDocument(title, [Segment(None, text)])


def extract_plain(text: str, title: str | None = None) -> ExtractedDocument:
    normalized = _normalize(text)
    if not normalized:
        raise ExtractionError("no_text")
    return ExtractedDocument(title, [Segment(None, normalized)])


def extract_pdf(body: bytes, *, max_pages: int = MAX_PDF_PAGES) -> ExtractedDocument:
    """Parse in a separate process with a timeout so a hostile PDF cannot hang or crash the
    worker. Encrypted PDFs and PDFs without a text layer (scanned) are rejected explicitly."""
    if not body.startswith(b"%PDF-"):
        raise ExtractionError("not_a_pdf")
    try:
        # Fixed argv (our own module, our interpreter); untrusted bytes only travel over stdin.
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "app.tools.pdf_worker", str(max_pages)],
            input=body,
            capture_output=True,
            timeout=PDF_TIMEOUT_SECONDS,
            check=False,
            cwd=BACKEND_DIR,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExtractionError("pdf_timeout") from exc
    if completed.returncode != 0:
        raise ExtractionError("pdf_unreadable")
    result = json.loads(completed.stdout)
    if result.get("error"):
        raise ExtractionError(str(result["error"]))
    pages: list[str] = result["pages"]
    segments = [Segment(f"page {i}", _normalize(t)) for i, t in enumerate(pages, 1) if _normalize(t)]
    if sum(len(s.text) for s in segments) < MIN_CHARS_PER_PAGE * max(1, len(pages)):
        raise ExtractionError("no_text_layer")
    return ExtractedDocument(result.get("title") or None, segments, len(pages))


def extract(body: bytes, content_type: str, charset: str | None = None) -> ExtractedDocument:
    if content_type == "application/pdf":
        return extract_pdf(body)
    if content_type in ("text/html", "application/xhtml+xml"):
        return extract_html(decode(body, charset))
    if content_type in ("text/plain", "text/markdown"):
        return extract_plain(decode(body, charset))
    raise ExtractionError("unsupported_content_type")

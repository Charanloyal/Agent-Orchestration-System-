"""Passage chunking shared by web evidence and uploads (ADR 0031).

Passages end on a paragraph, line or sentence boundary, never mid-word or mid-sentence, so
every cited passage reads as complete text. A single sentence longer than the hard limit is
the only thing ever split inside, at a word boundary.
"""

import re

PASSAGE_TARGET_CHARS = 1600
PASSAGE_MAX_CHARS = 2000
MAX_PASSAGES_PER_SOURCE = 8

# A sentence ends at . ! ? (optionally followed by a closing quote or bracket) and whitespace,
# unless the period belongs to a common abbreviation or an initial.
_BOUNDARY = re.compile(r"(?<=[.!?])([\"'\u201d\u2019)\]]*)\s+")
_ABBREVIATION = re.compile(
    r"(?:\b(?:e\.g|i\.e|etc|vs|Dr|Mr|Ms|Mrs|Prof|Inc|Ltd|No|Fig|al|approx)|\b[A-Z])\.$"
)


def normalise(text: str) -> str:
    """Unify line endings, drop trailing spaces and soft hyphens, re-join words hyphenated
    across a line break, and collapse runs of blank lines and spaces."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00ad", "").replace("\u00a0", " ")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def sentences(text: str) -> list[str]:
    out: list[str] = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        if _ABBREVIATION.search(text[: match.start()].rstrip("\"'\u201d\u2019)]")):
            continue
        out.append(text[start : match.start() + len(match.group(1))].strip())
        start = match.end()
    if text[start:].strip():
        out.append(text[start:].strip())
    return [s for s in out if s]


def _split_long(sentence: str) -> list[str]:
    """Only for a single sentence longer than PASSAGE_MAX_CHARS: cut at word boundaries."""
    parts = []
    while len(sentence) > PASSAGE_MAX_CHARS:
        cut = sentence.rfind(" ", 0, PASSAGE_MAX_CHARS)
        cut = cut if cut > PASSAGE_MAX_CHARS // 2 else PASSAGE_MAX_CHARS
        parts.append(sentence[:cut].strip())
        sentence = sentence[cut:].strip()
    return [*parts, sentence] if sentence else parts


def _units(text: str) -> list[tuple[str, str]]:
    """(separator before it, unit): lines within paragraphs; an over-long line becomes its
    sentences, and only an over-long single sentence is cut at word boundaries."""
    units: list[tuple[str, str]] = []
    for p_index, paragraph in enumerate(text.split("\n\n")):
        lines = [line.strip() for line in paragraph.split("\n") if line.strip()]
        for l_index, line in enumerate(lines):
            separator = ("\n" if l_index else "\n\n") if (p_index or l_index) else ""
            pieces = [line] if len(line) <= PASSAGE_TARGET_CHARS else sentences(line)
            pieces = [part for piece in pieces for part in _split_long(piece)]
            for s_index, piece in enumerate(pieces):
                units.append((separator if s_index == 0 else " ", piece))
    return units


def split_passages(text: str, *, limit: int | None = MAX_PASSAGES_PER_SOURCE) -> list[str]:
    """Pack whole paragraphs, lines and sentences into passages of about PASSAGE_TARGET_CHARS
    (at most PASSAGE_MAX_CHARS) so each passage is a complete, citable unit."""
    passages: list[str] = []
    current = ""
    for separator, unit in _units(normalise(text)):
        if current and len(current) + len(separator) + len(unit) > PASSAGE_TARGET_CHARS:
            passages.append(current)
            current = unit
        else:
            current = f"{current}{separator}{unit}" if current else unit
    if current:
        passages.append(current)
    return passages if limit is None else passages[:limit]


def clip(text: str, limit: int = PASSAGE_MAX_CHARS) -> str:
    """Whole sentences up to `limit` characters (a passage stored before sentence-aware
    chunking may be longer); never ends mid-word."""
    if len(text) <= limit:
        return text
    kept = ""
    for sentence in sentences(text):
        if len(kept) + len(sentence) + 1 > limit:
            break
        kept = f"{kept} {sentence}" if kept else sentence
    return kept or _split_long(text)[0]

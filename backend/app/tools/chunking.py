"""Passage chunking shared by web evidence and uploads."""

PASSAGE_TARGET_CHARS = 1200
MAX_PASSAGES_PER_SOURCE = 8


def _chunks(paragraph: str) -> list[str]:
    chunks = []
    while len(paragraph) > PASSAGE_TARGET_CHARS:
        cut = paragraph.rfind(" ", 0, PASSAGE_TARGET_CHARS)
        if cut < PASSAGE_TARGET_CHARS // 2:
            cut = PASSAGE_TARGET_CHARS
        chunks.append(paragraph[:cut].strip())
        paragraph = paragraph[cut:].strip()
    if paragraph:
        chunks.append(paragraph)
    return chunks


def split_passages(text: str, *, limit: int | None = MAX_PASSAGES_PER_SOURCE) -> list[str]:
    """Paragraph-aware chunking: pack paragraphs (split if oversized) into passages of at most
    PASSAGE_TARGET_CHARS so each passage is a citable, reviewable unit."""
    passages: list[str] = []
    current = ""
    for paragraph in (p.strip() for p in text.replace("\r\n", "\n").split("\n\n")):
        for chunk in _chunks(paragraph):
            if current and len(current) + 1 + len(chunk) > PASSAGE_TARGET_CHARS:
                passages.append(current)
                current = chunk
            else:
                current = f"{current}\n{chunk}" if current else chunk
    if current:
        passages.append(current)
    return passages if limit is None else passages[:limit]

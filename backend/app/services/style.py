"""Writing Style Studio: measured style metrics and a fact-locked, persona-aware rewrite.

Everything here is deterministic and explainable. The metrics describe the text (how much
sentence length varies, how varied the vocabulary is, how much boilerplate it contains, whether
facts survived a rewrite); they are not a prediction of who or what wrote it, and nothing here
claims to defeat AI-detection tools.

The rewrite only touches wording that carries no facts: numbers, dates, percentages, quoted
text, citations and URLs are locked, and any change that would alter them is rejected.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Literal

Persona = Literal["journalist", "academic", "executive", "technical"]
PERSONAS: tuple[Persona, ...] = ("journalist", "academic", "executive", "technical")

MAX_CHARS = 50_000
_RSQUO, _LDQUO, _RDQUO = "\u2019", "\u201c", "\u201d"
_WORD = re.compile(rf"[A-Za-z][A-Za-z'{_RSQUO}-]*|\d[\d,.]*%?")
_SENTENCE_END = re.compile(rf"(?<=[.!?])[\"{_RDQUO}{_RSQUO})\]]*\s+(?=[\"{_LDQUO}(\[]?[A-Z0-9])")
# Facts that a rewrite must keep exactly: numbers (with units/percent), quoted text,
# bracketed citations and URLs.
_FACTS = re.compile(
    r"https?://\S+"
    r"|\[[^\]\n]{1,80}\]"
    r"|[\"“][^\"”\n]{1,400}[\"”]"
    r"|\d[\d,.]*\s?(?:%|percent)?"
)

# Stock phrases that make prose read as boilerplate. Lower-case; matched on word boundaries.
# Each maps to a plainer replacement ("" removes the phrase).
_PHRASES: dict[str, str] = {
    "it is important to note that": "",
    "it is worth noting that": "",
    "it should be noted that": "",
    "it is crucial to note that": "",
    "needless to say,": "",
    "in today's fast-paced world,": "",
    "in today's digital age,": "",
    "in the ever-evolving landscape of": "in",
    "in the realm of": "in",
    "when it comes to": "for",
    "at the end of the day,": "",
    "in conclusion,": "",
    "to sum up,": "",
    "all in all,": "",
    "last but not least,": "finally,",
    "first and foremost,": "first,",
    "moreover,": "",
    "furthermore,": "",
    "additionally,": "",
    "in addition,": "",
    "consequently,": "so",
    "nevertheless,": "still,",
    "delve into": "examine",
    "delves into": "examines",
    "delved into": "examined",
    "dive into": "look at",
    "dive deep into": "look closely at",
    "a testament to": "evidence of",
    "stands as a testament to": "shows",
    "serves as a testament to": "shows",
    "plays a crucial role in": "matters for",
    "plays a pivotal role in": "matters for",
    "plays a vital role in": "matters for",
    "a pivotal role": "a central role",
    "pivotal": "central",
    "paramount": "essential",
    "tapestry": "mix",
    "rich tapestry": "wide mix",
    "symphony of": "mix of",
    "ever-evolving": "changing",
    "ever-changing": "changing",
    "cutting-edge": "new",
    "state-of-the-art": "current",
    "game-changer": "major change",
    "game-changing": "major",
    "unlock the potential of": "make use of",
    "unlock the power of": "use",
    "harness the power of": "use",
    "leverage": "use",
    "leverages": "uses",
    "leveraging": "using",
    "utilize": "use",
    "utilizes": "uses",
    "utilizing": "using",
    "foster": "build",
    "fosters": "builds",
    "fostering": "building",
    "underscores": "shows",
    "underscore": "show",
    "highlights the importance of": "shows why",
    "seamlessly": "smoothly",
    "seamless": "smooth",
    "robust": "strong",
    "navigate the complexities of": "deal with",
    "the complexities of": "the details of",
    "a myriad of": "many",
    "myriad": "many",
    "plethora of": "many",
    "embark on a journey": "start",
    "embark on": "start",
    "a wide range of": "many",
    "a variety of": "several",
    "in order to": "to",
    "due to the fact that": "because",
    "for the purpose of": "for",
    "with regard to": "on",
    "in terms of": "for",
    "each and every": "every",
    "it goes without saying that": "",
    "the landscape of": "the field of",
    "landscape": "field",
    "realm": "area",
    "intricate": "complex",
    "meticulous": "careful",
    "meticulously": "carefully",
    "bustling": "busy",
    "vibrant": "lively",
    "commendable": "good",
    "noteworthy": "notable",
}
# Persona-specific choices for transitions academic prose legitimately uses.
_PERSONA_KEEP: dict[Persona, frozenset[str]] = {
    "academic": frozenset({"in addition,", "consequently,", "nevertheless,", "furthermore,", "moreover,"}),
    "journalist": frozenset(),
    "executive": frozenset(),
    "technical": frozenset({"robust", "consequently,"}),
}
_PHRASE_PATTERN = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(p) for p in sorted(_PHRASES, key=len, reverse=True)) + r")(?![\w-])",
    re.IGNORECASE,
)
_NOT_ONLY = re.compile(r"\bnot only\b(.{3,120}?),?\s+but also\b", re.IGNORECASE)
_SPLIT_AT = re.compile(r",\s+(and|but|so)\s+|;\s+()")


@dataclass(frozen=True)
class Sentence:
    text: str
    words: int
    phrases: tuple[str, ...]


@dataclass(frozen=True)
class StyleReport:
    words: int
    sentences: int
    paragraphs: int
    mean_sentence_words: float
    sentence_length_cv: float  # coefficient of variation of sentence lengths (stdev / mean)
    shortest_sentence: int
    longest_sentence: int
    vocabulary_mattr: float  # moving-average type-token ratio, window 50
    word_entropy_bits: float  # Shannon entropy of word frequencies
    stock_phrases: int
    stock_phrases_per_1000_words: float
    paragraph_length_cv: float
    flagged: tuple[int, ...]  # indexes of sentences with stock phrases or over 40 words
    sentence_list: tuple[Sentence, ...] = field(repr=False)


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]


def sentences(paragraph: str) -> list[str]:
    flat = re.sub(r"\s+", " ", paragraph).strip()
    return [s.strip() for s in _SENTENCE_END.split(flat) if s.strip()]


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def facts(text: str) -> Counter[str]:
    """The fact tokens a rewrite must preserve, normalised for whitespace."""
    return Counter(re.sub(r"\s+", " ", m.group(0)).strip().rstrip(".,;:") for m in _FACTS.finditer(text))


def stock_phrases(text: str) -> list[str]:
    hits = [m.group(1).lower() for m in _PHRASE_PATTERN.finditer(text)]
    hits += ["not only … but also"] * len(_NOT_ONLY.findall(text))
    return hits


def _cv(values: list[int]) -> float:
    if len(values) < 2 or mean(values) == 0:
        return 0.0
    return round(pstdev(values) / mean(values), 3)


def _mattr(tokens: list[str], window: int = 50) -> float:
    if not tokens:
        return 0.0
    if len(tokens) <= window:
        return round(len(set(tokens)) / len(tokens), 3)
    counts = Counter(tokens[:window])
    total = len(counts)
    for i in range(window, len(tokens)):
        counts[tokens[i]] += 1
        old = tokens[i - window]
        counts[old] -= 1
        if counts[old] == 0:
            del counts[old]
        total += len(counts)
    return round(total / (len(tokens) - window + 1), 3)


def _entropy(tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    counts = Counter(tokens)
    n = len(tokens)
    return round(-sum(c / n * math.log2(c / n) for c in counts.values()), 3)


def analyze(text: str) -> StyleReport:
    paras = paragraphs(text)
    sents: list[Sentence] = []
    per_paragraph: list[int] = []
    for para in paras:
        found = sentences(para)
        per_paragraph.append(len(found))
        for sentence in found:
            sents.append(Sentence(sentence, len(words(sentence)), tuple(stock_phrases(sentence))))
    lengths = [s.words for s in sents if s.words]
    tokens = [w.lower() for w in words(text)]
    phrase_count = sum(len(s.phrases) for s in sents)
    return StyleReport(
        words=len(tokens),
        sentences=len(sents),
        paragraphs=len(paras),
        mean_sentence_words=round(mean(lengths), 1) if lengths else 0.0,
        sentence_length_cv=_cv(lengths),
        shortest_sentence=min(lengths, default=0),
        longest_sentence=max(lengths, default=0),
        vocabulary_mattr=_mattr(tokens),
        word_entropy_bits=_entropy(tokens),
        stock_phrases=phrase_count,
        stock_phrases_per_1000_words=round(1000 * phrase_count / len(tokens), 1) if tokens else 0.0,
        paragraph_length_cv=_cv(per_paragraph),
        flagged=tuple(i for i, s in enumerate(sents) if s.phrases or s.words > 40),
        sentence_list=tuple(sents),
    )


@dataclass(frozen=True)
class FactLock:
    total: int
    preserved: int
    missing: tuple[str, ...]


def fact_lock(original: str, rewritten: str) -> FactLock:
    before, after = facts(original), facts(rewritten)
    missing = before - after
    total = sum(before.values())
    return FactLock(total=total, preserved=total - sum(missing.values()), missing=tuple(sorted(missing)))


def _capitalise_start(sentence: str) -> str:
    stripped = sentence.lstrip()
    if not stripped:
        return sentence
    return stripped[0].upper() + stripped[1:]


def _replace_phrases(sentence: str, persona: Persona) -> str:
    keep = _PERSONA_KEEP[persona]

    def swap(match: re.Match[str]) -> str:
        found = match.group(1)
        if found.lower() in keep:
            return found
        replacement = _PHRASES[found.lower()]
        if found[:1].isupper() and replacement:
            replacement = replacement[0].upper() + replacement[1:]
        return replacement

    out = _PHRASE_PATTERN.sub(swap, sentence)
    out = _NOT_ONLY.sub(lambda m: f"{m.group(1).strip()} and also", out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    out = re.sub(r"^[,;:]\s*", "", out)
    return _capitalise_start(out)


def _inside_quote_or_brackets(text: str, index: int) -> bool:
    head = text[:index]
    return (
        head.count('"') % 2 == 1
        or head.count("“") > head.count("”")
        or head.count("[") > head.count("]")
        or head.count("(") > head.count(")")
    )


def _split_sentence(sentence: str, min_part: int) -> list[str]:
    """Split once at a clause boundary (", and", ", but", ";") outside quotes and brackets,
    when both halves keep at least `min_part` words."""
    for match in _SPLIT_AT.finditer(sentence):
        if _inside_quote_or_brackets(sentence, match.start()):
            continue
        left, right = sentence[: match.start()].strip(), sentence[match.end() :].strip()
        if len(words(left)) >= min_part and len(words(right)) >= min_part:
            end = sentence[-1] if sentence[-1] in ".!?" else "."
            # "and" joins; "but" and "so" carry meaning and start the new sentence.
            conjunction = (match.group(1) or "").lower()
            right = f"{conjunction} {right}" if conjunction in {"but", "so"} else right
            return [left.rstrip(",;") + ".", _capitalise_start(right).rstrip(".!?") + end]
    return [sentence]


_SPLIT_RULES: dict[Persona, tuple[int, int]] = {
    # (split sentences longer than this many words, minimum words per half)
    "journalist": (18, 4),
    "executive": (16, 4),
    "technical": (26, 6),
    "academic": (32, 8),
}


@dataclass(frozen=True)
class Rewrite:
    text: str
    passes: int
    changed_sentences: int
    rejected_changes: int


def rewrite(text: str, persona: Persona = "journalist", max_passes: int = 3) -> Rewrite:
    """Deterministic, persona-aware rewrite in up to `max_passes` passes:

    1. replace stock phrases with plain wording and undo "not only … but also";
    2. vary rhythm by splitting long sentences at clause boundaries (how long depends on the
       persona), so short and long sentences alternate.

    Each sentence change is kept only if the sentence's facts are unchanged; passes stop when
    a pass changes nothing.
    """
    long_after, min_part = _SPLIT_RULES[persona]
    current = paragraphs(text)
    changed = rejected = 0
    passes = 0
    long_seen = 0
    for pass_number in range(max_passes):
        passes += 1
        pass_changes = 0
        new_paragraphs: list[str] = []
        for para in current:
            out: list[str] = []
            for sentence in sentences(para):
                candidate = _replace_phrases(sentence, persona)
                parts = [candidate]
                # Rhythm only in the first pass, and only for every other long sentence, so
                # short and long sentences alternate instead of all becoming short.
                if pass_number == 0 and len(words(candidate)) > long_after:
                    if long_seen % 2 == 0:
                        parts = _split_sentence(candidate, min_part)
                    long_seen += 1
                proposal = " ".join(parts)
                if proposal == sentence:
                    out.append(sentence)
                    continue
                if facts(proposal) != facts(sentence) or not words(proposal):
                    rejected += 1
                    out.append(sentence)
                    continue
                pass_changes += 1
                out.extend(parts)
            new_paragraphs.append(" ".join(out))
        current = new_paragraphs
        changed += pass_changes
        if pass_changes == 0:
            break
    return Rewrite(
        text="\n\n".join(current), passes=passes, changed_sentences=changed, rejected_changes=rejected
    )

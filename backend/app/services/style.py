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
from collections.abc import Callable
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
    "plays a key role in": "matters for",
    "play a crucial role in": "matter for",
    "play a pivotal role in": "matter for",
    "play a vital role in": "matter for",
    "play a key role in": "matter for",
    "plays a pivotal role in shaping": "shapes",
    "plays a crucial role in shaping": "shapes",
    "plays a key role in shaping": "shapes",
    "play a pivotal role in shaping": "shape",
    "play a crucial role in shaping": "shape",
    "play a key role in shaping": "shape",
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
    "foundational": "core",
    "transformative": "major",
    "revolutionize": "change",
    "revolutionise": "change",
    "revolutionizing": "changing",
    "revolutionising": "changing",
    "groundbreaking": "new",
    "holistic": "complete",
    "paradigm shift": "major shift",
    "trajectory": "direction",
    "underpins": "supports",
    "underpin": "support",
    "bolster": "strengthen",
    "bolsters": "strengthens",
    "spearhead": "lead",
    "spearheads": "leads",
    "spearheading": "leading",
    "multifaceted": "complex",
    "rapidly evolving": "fast-changing",
    "crucial": "key",
    "in today's world,": "",
}
# Persona-specific choices for transitions academic prose legitimately uses.
_PERSONA_KEEP: dict[Persona, frozenset[str]] = {
    "academic": frozenset({"in addition,", "consequently,", "nevertheless,", "furthermore,", "moreover,"}),
    "journalist": frozenset(),
    "executive": frozenset(),
    "technical": frozenset({"robust", "consequently,"}),
}
_CONTRACTIONS = {
    "don't": "do not",
    "doesn't": "does not",
    "didn't": "did not",
    "can't": "cannot",
    "won't": "will not",
    "isn't": "is not",
    "aren't": "are not",
    "wasn't": "was not",
    "it's": "it is",
    "that's": "that is",
    "we're": "we are",
    "they're": "they are",
    "there's": "there is",
}
_HEDGES = {
    "arguably": "",
    "basically": "",
    "really": "",
    "very": "",
    "quite": "",
    "somewhat": "",
    "rather": "",
    "it seems that": "",
    "it appears that": "",
    "a number of": "several",
    "at this point in time": "now",
    "in the near future": "soon",
    "the fact that": "that",
}
# Each voice's own vocabulary, applied after the shared stock phrases.
_PERSONA_PHRASES: dict[Persona, dict[str, str]] = {
    "academic": {
        **_CONTRACTIONS,
        **{k.replace("'", _RSQUO): v for k, v in _CONTRACTIONS.items()},
        "a lot of": "many",
        "lots of": "many",
        "huge": "substantial",
        "big": "large",
        "kind of": "somewhat",
    },
    "journalist": {
        "individuals": "people",
        "commence": "start",
        "commenced": "started",
        "approximately": "about",
        "purchase": "buy",
        "purchased": "bought",
        "assist": "help",
        "in the event that": "if",
        "prior to": "before",
        "subsequently": "later",
        "numerous": "many",
        "a number of": "several",
    },
    "executive": {
        **_HEDGES,
        "approximately": "about",
        "in the event that": "if",
        "prior to": "before",
        "going forward": "from now on",
    },
    "technical": {
        "basically": "",
        "really": "",
        "very": "",
        "simply": "",
        "quite": "",
        "approximately": "about",
    },
}
_PERSONA_PATTERNS: dict[Persona, re.Pattern[str]] = {
    persona: re.compile(
        r"(?<![\w-])(" + "|".join(re.escape(p) for p in sorted(table, key=len, reverse=True)) + r")(?![\w-])",
        re.IGNORECASE,
    )
    for persona, table in _PERSONA_PHRASES.items()
}
_PHRASE_PATTERN = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(p) for p in sorted(_PHRASES, key=len, reverse=True)) + r")(?![\w-])",
    re.IGNORECASE,
)
_NOT_ONLY = re.compile(r"\bnot only\b(.{3,120}?),?\s+but also\b", re.IGNORECASE)
_SPLIT_AT = re.compile(r",\s+(and|but|so)\s+|;\s+()")

# Sentence openers that mark templated prose. Each is removed or restructured at the start of a
# sentence; the rest of the sentence, and every fact in it, stays.
_START = r"(?:^|(?<=[.!?]\s))"
_TODAY_OPENER = re.compile(
    _START + r"In today's(?: [\w-]+){0,4} (?:world|age|era|landscape|environment|economy|market|society"
    r"|climate|field|ecosystem|space|arena|context),\s*",
    re.IGNORECASE | re.MULTILINE,
)
_ERA_OPENER = re.compile(
    _START + r"(?:In an? (?:era|age|world|time) (?:of|where|when|in which) [^,]{3,100}"
    r"|In the (?:rapidly |ever-|constantly |fast-)?(?:evolving|changing|shifting)"
    r" (?:world|landscape|field|realm|arena) of [^,]{3,80}),\s*",
    re.IGNORECASE | re.MULTILINE,
)
_SUMMARY_OPENER = re.compile(
    _START + r"(?:In summary|To conclude|In closing|Ultimately|Overall|In essence|All things considered"
    r"|Notably|Importantly|Crucially|Indeed|Interestingly),\s*",
    re.IGNORECASE | re.MULTILINE,
)
_IT_IS_OPENER = re.compile(
    _START + r"It is (?!important to note that|worth noting that|crucial to note that)"
    r"(?:important|crucial|essential|vital|key|critical|imperative|worth remembering)"
    r" (?:to (?:note|remember|recogni[sz]e|understand|emphasi[sz]e|highlight|consider) )?that\s+",
    re.IGNORECASE | re.MULTILINE,
)
_AS_OPENER = re.compile(
    r"^As (?P<subj>[\w'-]+(?: [\w'-]+){0,3}?)"
    r" (?P<verb>(?:continue to |begin to |seek to |race to |strive to )?"
    r"(?:delve into|delves into|navigate|navigates|embrace|embraces|grapple with|grapples with"
    r"|explore|explores|adapt to|adapts to|invest in|invests in|pursue|pursues|adopt|adopts"
    r"|look to|looks to))"
    r" (?P<obj>[^,]{3,120}),\s*(?P<rest>.+)$",
    re.IGNORECASE,
)
_AUX = "does|do|did|is|are|was|were|can|could|will|would|has|have"
_NOT_ONLY_INVERTED = re.compile(
    rf"^Not only (?P<aux>{_AUX}) (?P<body>.+?),?\s+but (?:(?P<pron>it|they|this|these|we|he|she|you) )?"
    rf"(?P<aux2>(?:{_AUX}) )?also (?P<tail>.+)$",
    re.IGNORECASE,
)
_PILLARS = re.compile(
    r"^(?:The )?(?:key|core|main|primary|major|several|three|four|five)"
    r" (?P<what>pillars|drivers|factors|forces|components|elements|aspects|trends|enablers)"
    r"(?: (?:driving|behind|of|shaping|underpinning|powering"
    r"|fueling|fuelling))? (?P<obj>[^:]{3,100}?) (?:include|are|involve)(?: the following)?:$",
    re.IGNORECASE,
)
_NOMINAL = re.compile(
    r"^The (?P<noun>deployment|development|implementation|adoption|creation|establishment|integration"
    r"|expansion|introduction|construction|acceleration|enhancement|improvement|optimi[sz]ation"
    r"|moderni[sz]ation|strengthening|use|utili[sz]ation|application|provision|delivery) of (?P<rest>.+)$",
    re.IGNORECASE,
)
_GERUND = {
    "deployment": "Deploying",
    "development": "Developing",
    "implementation": "Implementing",
    "adoption": "Adopting",
    "creation": "Creating",
    "establishment": "Establishing",
    "integration": "Integrating",
    "expansion": "Expanding",
    "introduction": "Introducing",
    "construction": "Building",
    "acceleration": "Accelerating",
    "enhancement": "Improving",
    "improvement": "Improving",
    "optimisation": "Optimising",
    "optimization": "Optimizing",
    "modernisation": "Modernising",
    "modernization": "Modernizing",
    "strengthening": "Strengthening",
    "use": "Using",
    "utilisation": "Using",
    "utilization": "Using",
    "application": "Applying",
    "provision": "Providing",
    "delivery": "Delivering",
}
_FINITE = frozenset(
    [
        "is",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "will",
        "can",
        "could",
        "would",
        "should",
        "may",
        "might",
        "must",
        "rose",
        "fell",
        "grew",
        "increased",
        "decreased",
        "remains",
        "remain",
        "shows",
        "show",
        "reached",
    ]
)
_VERBS = frozenset(
    [
        "cut",
        "reduce",
        "improve",
        "boost",
        "enhance",
        "increase",
        "lower",
        "raise",
        "provide",
        "offer",
        "deliver",
        "support",
        "enable",
        "help",
        "drive",
        "create",
        "make",
        "give",
        "save",
        "strengthen",
        "expand",
        "accelerate",
        "streamline",
        "simplify",
        "protect",
        "secure",
        "ensure",
        "address",
        "solve",
        "transform",
        "empower",
        "attract",
        "generate",
        "speed",
        "bring",
        "open",
        "allow",
        "lift",
        "build",
        "add",
        "keep",
        "cost",
        "serve",
        "meet",
        "shorten",
        "double",
        "halve",
    ]
)
_IRREGULAR_PAST = {
    "cut": "cut",
    "make": "made",
    "give": "gave",
    "drive": "drove",
    "bring": "brought",
    "build": "built",
    "keep": "kept",
    "speed": "sped",
    "cost": "cost",
    "meet": "met",
    "lift": "lifted",
}
_PRONOUNS = frozenset({"it", "they", "this", "these", "we", "he", "she", "you", "i"})
_OPENER_LABELS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("in today's … opener", _TODAY_OPENER),
    ("in an era of … opener", _ERA_OPENER),
    ("summary opener", _SUMMARY_OPENER),
    ("it is … that opener", _IT_IS_OPENER),
)


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
    blocks: tuple[BlockInfo, ...] = field(default=(), repr=False)


BlockKind = Literal["heading", "paragraph", "item", "quote", "verbatim", "blank"]


@dataclass(frozen=True)
class Block:
    """One Markdown block. `prefix` is the marker kept verbatim ("## ", "- ", "1. ")."""

    kind: BlockKind
    prefix: str
    text: str

    def render(self) -> str:
        return "" if self.kind == "blank" else self.prefix + self.text


@dataclass(frozen=True)
class BlockInfo:
    kind: BlockKind
    prefix: str
    text: str
    first_sentence: int
    sentence_count: int


_HEADING = re.compile(r"^(\s{0,3}#{1,6}[ \t]+)(.*?)\s*$")
_ITEM = re.compile(r"^(\s*(?:[-*+]|\d{1,3}[.)])[ \t]+)(.*?)\s*$")
_RULE_LINE = re.compile(r"^\s{0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_FENCE = re.compile(r"^\s{0,3}(```|~~~)")
_QUOTE_LINE = re.compile(r"^\s{0,3}>")
_TABLE_LINE = re.compile(r"^\s*\|")
_ENDS_SENTENCE = re.compile(rf"[.!?:][\"{_RDQUO}{_RSQUO})\]]*$")


def blocks(text: str) -> list[Block]:
    """Split Markdown or plain text into blocks, so a rewrite keeps headings, lists, quotes,
    code, tables and paragraph breaks exactly where they were.

    Lines of one paragraph are joined, except that a line ending a sentence followed by a line
    starting with a capital is kept as its own paragraph (text pasted with single line breaks).
    Block quotes, code, tables and rules are kept verbatim and never rewritten.
    """
    out: list[Block] = []
    para: list[str] = []
    fence: list[str] | None = None

    def flush() -> None:
        if para:
            out.append(Block("paragraph", "", " ".join(part.strip() for part in para)))
            para.clear()

    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if fence is not None:
            fence.append(line)
            if _FENCE.match(line):
                out.append(Block("verbatim", "", "\n".join(fence)))
                fence = None
            continue
        if _FENCE.match(line):
            flush()
            fence = [line]
        elif not line.strip():
            flush()
            out.append(Block("blank", "", ""))
        elif heading := _HEADING.match(line):
            flush()
            out.append(Block("heading", heading.group(1), heading.group(2)))
        elif _RULE_LINE.match(line) or _TABLE_LINE.match(line):
            flush()
            out.append(Block("verbatim", "", line.rstrip()))
        elif _QUOTE_LINE.match(line):
            flush()
            out.append(Block("quote", "", line.rstrip()))
        elif item := _ITEM.match(line):
            flush()
            out.append(Block("item", item.group(1), item.group(2)))
        elif not para and out and out[-1].kind == "item" and line[:1] in " \t":
            last = out[-1]
            out[-1] = Block("item", last.prefix, f"{last.text} {line.strip()}")
        else:
            if para and _ENDS_SENTENCE.search(para[-1].rstrip()) and line.lstrip()[:1].isupper():
                flush()
            para.append(line)
    flush()
    if fence is not None:
        out.append(Block("verbatim", "", "\n".join(fence)))
    return out


def render(parts: list[Block]) -> str:
    return "\n".join(block.render() for block in parts)


def sentences(paragraph: str) -> list[str]:
    flat = re.sub(r"\s+", " ", paragraph).strip()
    return [s.strip() for s in _SENTENCE_END.split(flat) if s.strip()]


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def facts(text: str) -> Counter[str]:
    """The fact tokens a rewrite must preserve, normalised for whitespace."""
    return Counter(re.sub(r"\s+", " ", m.group(0)).strip().rstrip(".,;:") for m in _FACTS.finditer(text))


def stock_phrases(text: str) -> list[str]:
    hits: list[str] = []
    covered: list[tuple[int, int]] = []
    for label, pattern in _OPENER_LABELS:
        for match in pattern.finditer(text):
            hits.append(label)
            covered.append(match.span())
    for sentence in sentences(text):
        if _AS_OPENER.match(sentence):
            hits.append("as … delve into opener")
        if _NOT_ONLY_INVERTED.match(sentence):
            hits.append("not only … but (inverted)")
    hits += [
        m.group(1).lower()
        for m in _PHRASE_PATTERN.finditer(text)
        if not any(start <= m.start() < end for start, end in covered)
    ]
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
    return round(total / (len(tokens) - window + 1) / window, 3)


def _entropy(tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    counts = Counter(tokens)
    n = len(tokens)
    return round(-sum(c / n * math.log2(c / n) for c in counts.values()), 3)


def analyze(text: str) -> StyleReport:
    """Measure the prose of `text`: paragraphs and list items. Headings, block quotes, code and
    tables are kept in `blocks` for display but are not the writer's sentences."""
    parts = blocks(text)
    sents: list[Sentence] = []
    per_paragraph: list[int] = []
    infos: list[BlockInfo] = []
    tokens: list[str] = []
    for block in parts:
        first = len(sents)
        if block.kind in ("paragraph", "item"):
            found = sentences(block.text)
            if block.kind == "paragraph":
                per_paragraph.append(len(found))
            for sentence in found:
                sents.append(Sentence(sentence, len(words(sentence)), tuple(stock_phrases(sentence))))
            tokens += [w.lower() for w in words(block.text)]
        infos.append(BlockInfo(block.kind, block.prefix, block.text, first, len(sents) - first))
    lengths = [s.words for s in sents if s.words]
    phrase_count = sum(len(s.phrases) for s in sents)
    return StyleReport(
        words=len(tokens),
        sentences=len(sents),
        paragraphs=len(per_paragraph),
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
        blocks=tuple(infos),
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

    def swapper(table: dict[str, str]) -> Callable[[re.Match[str]], str]:
        def swap(match: re.Match[str]) -> str:
            found = match.group(1)
            # Quoted words and citations are someone else's: never edited.
            if found.lower() in keep or _inside_quote_or_brackets(match.string, match.start()):
                return found
            replacement = table[found.lower()]
            if found[:1].isupper() and replacement:
                replacement = replacement[0].upper() + replacement[1:]
            return replacement

        return swap

    out = _PHRASE_PATTERN.sub(swapper(_PHRASES), sentence)
    out = _PERSONA_PATTERNS[persona].sub(swapper(_PERSONA_PHRASES[persona]), out)
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


def _third_person(verb: str) -> str:
    if verb.endswith(("s", "sh", "ch", "x", "z", "o")):
        return verb + "es"
    if verb.endswith("y") and verb[-2:-1] not in "aeiou":
        return verb[:-1] + "ies"
    return verb + "s"


def _past(verb: str) -> str:
    if verb in _IRREGULAR_PAST:
        return _IRREGULAR_PAST[verb]
    if verb.endswith("e"):
        return verb + "d"
    if verb.endswith("y") and verb[-2:-1] not in "aeiou":
        return verb[:-1] + "ied"
    return verb + "ed"


def _undo_inversion(sentence: str) -> str:
    """ "Not only does the plan cut costs, but it also improves uptime." becomes "The plan cuts
    costs. It also improves uptime." Left alone when the subject cannot be found safely."""
    match = _NOT_ONLY_INVERTED.match(sentence)
    if not match:
        return sentence
    aux = match.group("aux").lower()
    tokens = match.group("body").split()
    subject: list[str] | None = None
    predicate: list[str] = []
    if aux in {"does", "do", "did", "can", "could", "will", "would"}:
        for i in range(1, min(len(tokens), 7)):
            if tokens[i].lower() in _VERBS:
                subject, predicate = tokens[:i], tokens[i:]
                break
    elif len(tokens) > 1 and (
        tokens[0].lower() in _PRONOUNS or (tokens[0][:1].isupper() and tokens[0] != "The")
    ):
        subject, predicate = tokens[:1], tokens[1:]
    if not subject or not predicate:
        return sentence
    if aux == "does":
        predicate = [_third_person(predicate[0].lower()), *predicate[1:]]
    elif aux == "did":
        predicate = [_past(predicate[0].lower()), *predicate[1:]]
    elif aux != "do":
        predicate = [aux, *predicate]
    head = " ".join(subject)
    pronoun = match.group("pron")
    if not pronoun:
        if head.lower() in _PRONOUNS:
            pronoun = head
        else:
            pronoun = "they" if aux in {"do", "are", "were", "have"} else "it"
    aux2 = match.group("aux2") or ""
    first = f"{_capitalise_start(head)} {' '.join(predicate)}".rstrip(",") + "."
    return f"{first} {_capitalise_start(pronoun)} {aux2}also {match.group('tail')}"


def _rewrite_opener(sentence: str) -> str:
    out = sentence
    for pattern in (_TODAY_OPENER, _ERA_OPENER, _SUMMARY_OPENER, _IT_IS_OPENER):
        out = pattern.sub("", out, count=1)
    as_opener = _AS_OPENER.match(out)
    if as_opener:
        subject = _capitalise_start(as_opener.group("subj"))
        rest = _capitalise_start(as_opener.group("rest"))
        out = f"{subject} {as_opener.group('verb')} {as_opener.group('obj').strip()}. {rest}"
    pillars = _PILLARS.match(out)
    if pillars:
        verb = (
            "is driven by" if pillars.group("what").lower() in {"drivers", "forces", "trends"} else "rests on"
        )
        out = f"{_capitalise_start(pillars.group('obj'))} {verb}:"
    return _capitalise_start(out)


def _denominalise(item: str) -> str:
    """ "The deployment of GPU clusters" becomes "Deploying GPU clusters", for list items that
    are noun phrases (no finite verb), where the gerund reads as an action."""
    match = _NOMINAL.match(item)
    if not match or any(w.lower() in _FINITE for w in words(match.group("rest"))):
        return item
    return f"{_GERUND[match.group('noun').lower()]} {match.group('rest')}"


def _transform(sentence: str, persona: Persona, kind: BlockKind) -> tuple[str, tuple[str, ...]]:
    rules: list[str] = []
    out = sentence
    steps: list[tuple[str, Callable[[str], str]]] = []
    if kind != "heading":
        steps += [("opener", _rewrite_opener), ("not only … but", _undo_inversion)]
    if kind == "item":
        steps.append(("noun phrase to action", _denominalise))
    steps.append(("stock phrase", lambda s: _replace_phrases(s, persona)))
    for rule, step in steps:
        new = step(out)
        if new != out:
            rules.append(rule)
            out = new
    return out, tuple(rules)


_SPLIT_RULES: dict[Persona, tuple[int, int]] = {
    # (split sentences longer than this many words, minimum words per half)
    "journalist": (18, 4),
    "executive": (16, 4),
    "technical": (26, 6),
    "academic": (32, 8),
}


@dataclass(frozen=True)
class Change:
    before: str
    after: str
    rules: tuple[str, ...]
    accepted: bool  # False: rejected because it would have altered a fact


@dataclass(frozen=True)
class Rewrite:
    text: str
    passes: int
    changed_sentences: int
    rejected_changes: int
    changes: tuple[Change, ...] = ()


_JOINABLE = re.compile(r"^(?:It|They|This|These|He|She|We)\b")


def _prose_lengths(parts: list[Block]) -> list[int]:
    return [
        len(words(s)) for b in parts if b.kind in ("paragraph", "item") for s in sentences(b.text) if words(s)
    ]


def _rhythm(parts: list[Block], persona: Persona) -> tuple[list[Block], list[Change]]:
    """Vary sentence rhythm, guided by the measurement itself: split a long paragraph sentence
    at a clause boundary (how long counts as long depends on the persona), or join two short
    sentences when the second starts with a pronoun ("? costs. It also ?" -> "? costs, and it
    also ?"). A candidate is kept only if it raises the document's sentence-length variation,
    so the rewrite never flattens the rhythm it reports."""
    long_after, min_part = _SPLIT_RULES[persona]
    lengths = _prose_lengths(parts)
    out = list(parts)
    changes: list[Change] = []
    offset = 0
    for index, block in enumerate(out):
        if block.kind not in ("paragraph", "item"):
            continue
        units = [u for u in sentences(block.text) if words(u)]
        if block.kind == "item":
            offset += len(units)
            continue
        i = 0
        while i < len(units):
            current = units[i]
            options: list[
                tuple[list[str], int, str, str]
            ] = []  # (replacement, replaced count, before, after)
            if len(words(current)) > long_after:
                split = _split_sentence(current, min_part)
                if len(split) > 1:
                    options.append((split, 1, current, " ".join(split)))
            following = units[i + 1] if i + 1 < len(units) else None
            if (
                following is not None
                and current.endswith(".")
                and len(words(current)) <= 10
                and len(words(following)) <= 12
                and _JOINABLE.match(following)
            ):
                joined = f"{current[:-1]}, and {following[0].lower()}{following[1:]}"
                options.append(([joined], 2, f"{current} {following}", joined))
            base = _cv(lengths)
            best: tuple[float, list[str], int, str, str] | None = None
            for replacement, count, before, after in options:
                trial = (
                    lengths[: offset + i]
                    + [len(words(r)) for r in replacement]
                    + lengths[offset + i + count :]
                )
                gain = _cv(trial) - base
                if gain > 0.005 and facts(after) == facts(before) and (best is None or gain > best[0]):
                    best = (gain, replacement, count, before, after)
            if best is not None:
                _, replacement, count, before, after = best
                units[i : i + count] = replacement
                lengths[offset + i : offset + i + count] = [len(words(r)) for r in replacement]
                changes.append(Change(before, after, ("rhythm",), accepted=True))
                i += len(replacement)
            else:
                i += 1
        out[index] = Block(block.kind, block.prefix, " ".join(units))
        offset += len(units)
    return out, changes


def rewrite(text: str, persona: Persona = "journalist", max_passes: int = 3) -> Rewrite:
    """Deterministic, persona-aware rewrite in up to `max_passes` passes over the prose blocks
    (paragraphs, list items, headings); quotes, code and tables are never touched:

    1. remove templated openers ("In today's rapidly evolving …,", "In conclusion,"), turn
       "As X delve into Y, Z" into two sentences, undo "Not only does X …, but it also …";
    2. turn noun-phrase list items into actions ("The deployment of" -> "Deploying");
    3. replace stock phrases with plain wording;
    4. vary rhythm, guided by the measurement (`_rhythm`).

    Each sentence change is kept only if the sentence's facts are unchanged. Markdown
    structure is kept exactly: the same blocks, markers and blank lines, in the same order.
    """
    current = blocks(text)
    accepted: list[Change] = []
    rejected: dict[str, Change] = {}
    passes = 0
    for _ in range(max_passes):
        passes += 1
        pass_changes = 0
        updated: list[Block] = []
        for block in current:
            if block.kind not in ("heading", "paragraph", "item"):
                updated.append(block)
                continue
            out: list[str] = []
            units = [block.text] if block.kind == "heading" else sentences(block.text)
            for sentence in units:
                proposal, rules = _transform(sentence, persona, block.kind)
                if proposal == sentence:
                    out.append(sentence)
                    continue
                if facts(proposal) != facts(sentence) or not words(proposal):
                    rejected.setdefault(sentence, Change(sentence, proposal, rules, accepted=False))
                    out.append(sentence)
                    continue
                pass_changes += 1
                previous = next((c for c in accepted if c.after == sentence), None)
                if previous is not None:
                    accepted[accepted.index(previous)] = Change(
                        previous.before,
                        proposal,
                        tuple(dict.fromkeys((*previous.rules, *rules))),
                        accepted=True,
                    )
                else:
                    accepted.append(Change(sentence, proposal, rules, accepted=True))
                out.append(proposal)
            updated.append(Block(block.kind, block.prefix, " ".join(out)))
        current = updated
        if pass_changes == 0:
            break
    current, rhythm = _rhythm(current, persona)
    for change in rhythm:
        previous = next((c for c in accepted if c.after == change.before), None)
        if previous is None:
            accepted.append(change)
        else:
            accepted[accepted.index(previous)] = Change(
                previous.before, change.after, (*previous.rules, "rhythm"), accepted=True
            )
    return Rewrite(
        text=render(current),
        passes=passes,
        changed_sentences=len(accepted),
        rejected_changes=len(rejected),
        changes=(*accepted, *rejected.values()),
    )

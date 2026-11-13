"""Style studio with a language model (ADR 0029): the model rewrites the whole document in the
chosen voice; the result is accepted only if every fact survives and the Markdown structure is
unchanged, otherwise the model gets one correction round and then the built-in rules are used.
The rules then remove any stock phrase the model left in."""

import re
from dataclasses import dataclass

from app.providers.llm import LlmProvider
from app.services.style import Persona, blocks, fact_lock

MAX_MODEL_CHARS = 12_000

_VOICES: dict[Persona, str] = {
    "journalist": "a news reader: concrete, active verbs, plain words, short and long sentences mixed",
    "academic": "an academic reader: precise and formal, full words instead of contractions, careful hedging",
    "executive": "a busy executive: direct, no hedges or filler, the point of each paragraph first",
    "technical": "an engineer: precise terms, no vague intensifiers, one idea per sentence",
}

_SYSTEM = """You edit prose for {voice}.
Rewrite the Markdown document the user sends. Rules:
- Keep every heading, list item, block quote, code block and table, in the same order, with the
  same Markdown markers. Keep paragraph breaks.
- Copy exactly every number, date, percentage, quoted passage, bracketed citation such as [1],
  and URL. Never add facts, claims, names, figures or sources.
- Remove templated phrasing ("In today's rapidly evolving ...", "delve into", "a testament to",
  "It is important to note that", "In conclusion,", "Not only ... but also").
- Vary sentence length: mix short sentences with longer ones.
Return only the rewritten Markdown, with no commentary and no code fences."""

_FENCE = re.compile(r"^```(?:markdown|md)?\s*\n(.*)\n```\s*$", re.S)


@dataclass(frozen=True)
class ModelRewrite:
    text: str | None  # None: rejected or failed; use the rules
    note: str


def _shape(text: str) -> list[str]:
    return [b.kind for b in blocks(text) if b.kind in ("heading", "item", "quote", "verbatim")]


def model_rewrite(llm: LlmProvider, text: str, persona: Persona) -> ModelRewrite:
    if len(text) > MAX_MODEL_CHARS:
        return ModelRewrite(
            None, f"longer than {MAX_MODEL_CHARS:,} characters: rewritten with the built-in rules"
        )
    system = _SYSTEM.format(voice=_VOICES[persona])
    user = text
    problem = ""
    for _attempt in range(2):
        try:
            result = llm.complete(
                system=system,
                user=user,
                json_output=False,
                max_output_tokens=min(8000, len(text) // 2 + 1500),
            )
        except Exception as exc:  # provider down or key rejected: the rules still work
            return ModelRewrite(
                None, f"model unavailable ({str(exc)[:120]}): rewritten with the built-in rules"
            )
        out = result.text.strip()
        fenced = _FENCE.match(out)
        out = fenced.group(1).strip() if fenced else out
        lock = fact_lock(text, out)
        if lock.missing:
            problem = "it changed or dropped: " + ", ".join(lock.missing[:10])
        elif _shape(out) != _shape(text):
            problem = "it changed the headings, lists, quotes or code"
        else:
            return ModelRewrite(
                out + ("\n" if text.endswith("\n") else ""), f"rewritten by {result.usage.model}"
            )
        user = (
            f"{text}\n\n---\nYour previous rewrite was rejected because {problem}. "
            "Rewrite the document above again and keep all of it exactly."
        )
    return ModelRewrite(
        None, f"the model's rewrite was rejected ({problem}): rewritten with the built-in rules"
    )

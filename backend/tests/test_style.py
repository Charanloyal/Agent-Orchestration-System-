"""Writing Style Studio: metrics are computed exactly, and a rewrite never changes a fact."""

import pytest

from app.services import style
from app.services.style import PERSONAS, analyze, blocks, fact_lock, facts, rewrite, stock_phrases

BOILERPLATE = (
    "It is important to note that the platform processed 1,250 requests in 2024. "
    "Moreover, the team will delve into the results, and the review will cover every region. "
    "Furthermore, this pivotal change is a testament to the vendor's focus on reliability. "
    'The CEO said "we doubled uptime to 99.9%" in March [3].\n\n'
    "In conclusion, the platform is not only fast but also cheap, and it scales to 40 nodes."
)


def test_metrics_follow_their_definitions() -> None:
    report = analyze("One two three four. One two three four five six seven eight.\n\nNine ten.")
    assert (report.words, report.sentences, report.paragraphs) == (14, 3, 2)
    assert (report.shortest_sentence, report.longest_sentence) == (2, 8)
    assert report.mean_sentence_words == pytest.approx(14 / 3, abs=0.05)
    # lengths 4, 8, 2: population sigma 2.494 over mean 4.667
    assert report.sentence_length_cv == pytest.approx(0.535, abs=0.001)
    assert report.paragraph_length_cv == pytest.approx(1 / 3, abs=0.001)
    assert 0 < report.vocabulary_mattr <= 1 and report.word_entropy_bits > 0


def test_identical_sentence_lengths_have_zero_variation() -> None:
    assert analyze("A b c d. E f g h. I j k l.").sentence_length_cv == 0.0
    assert analyze("").words == 0


def test_stock_phrases_are_found_and_sentences_flagged() -> None:
    report = analyze(BOILERPLATE)
    found = set(stock_phrases(BOILERPLATE))
    assert {
        "it is important to note that",
        "moreover,",
        "delve into",
        "a testament to",
        "in conclusion,",
    } <= found
    assert "not only … but also" in found
    assert report.stock_phrases >= 8 and report.stock_phrases_per_1000_words > 0
    assert 0 in report.flagged and len(report.flagged) >= 4


def test_facts_cover_numbers_quotes_citations_and_urls() -> None:
    found = facts(BOILERPLATE + " See https://example.org/report.")
    assert {
        "1,250",
        "2024",
        "40",
        "[3]",
        '"we doubled uptime to 99.9%"',
        "https://example.org/report",
    } <= set(found)


@pytest.mark.parametrize("persona", PERSONAS)
def test_rewrite_keeps_every_fact_for_every_persona(persona: str) -> None:
    result = rewrite(BOILERPLATE, persona)  # type: ignore[arg-type]
    lock = fact_lock(BOILERPLATE, result.text)
    assert lock.preserved == lock.total and lock.missing == ()
    assert result.text.count("\n\n") == BOILERPLATE.count("\n\n"), "paragraphs are kept"


def test_journalist_rewrite_removes_boilerplate_and_varies_rhythm() -> None:
    before = analyze(BOILERPLATE)
    result = rewrite(BOILERPLATE, "journalist")
    after = analyze(result.text)
    assert after.stock_phrases < before.stock_phrases
    assert "delve" not in result.text.lower() and "testament" not in result.text.lower()
    assert result.text.startswith("The platform processed 1,250 requests in 2024.")
    assert "not only" not in result.text
    assert after.sentence_length_cv > before.sentence_length_cv, "sentence lengths vary more"
    assert result.changed_sentences > 0 and 1 <= result.passes <= 3


UNIFORM = " ".join(
    f"The {name} team reviewed the quarterly figures for region {n}, "
    "and the analysts published a short note on the outcome."
    for n, name in enumerate(["north", "south", "east", "west"], start=1)
)


def test_uniform_long_sentences_get_a_varied_rhythm() -> None:
    before = analyze(UNIFORM)
    result = rewrite(UNIFORM, "journalist")
    after = analyze(result.text)
    assert before.sentence_length_cv == 0.0
    assert after.sentences == 6, "every other long sentence is split at its clause boundary"
    assert after.sentence_length_cv > 0.3
    assert fact_lock(UNIFORM, result.text).missing == ()


def test_academic_keeps_its_legitimate_transitions() -> None:
    text = "Moreover, the sample was small. In addition, the period was short."
    assert rewrite(text, "academic").text == text
    assert rewrite(text, "journalist").text == "The sample was small. The period was short."


def test_quotes_and_brackets_are_never_split_or_edited() -> None:
    text = 'He said "we leverage data, and we foster trust" when asked [ref 2; see notes, and appendix].'
    result = rewrite(text, "executive")
    assert '"we leverage data, and we foster trust"' in result.text
    assert "[ref 2; see notes, and appendix]" in result.text


def test_but_and_so_survive_a_split() -> None:
    text = (
        "The new pricing applies to every customer in every region of the world, "
        "but the old contracts stay valid until they end."
    )
    assert "But the old contracts stay valid" in rewrite(text, "journalist").text


def test_fact_lock_reports_what_a_rewrite_lost() -> None:
    lock = fact_lock("Revenue grew 12% in 2025 [1].", "Revenue grew in 2025.")
    assert lock.total == 3 and lock.preserved == 1 and set(lock.missing) == {"12%", "[1]"}


MARKDOWN = (
    "# Sovereign AI in India\n\n"
    "In today's rapidly evolving technological landscape, India is building its own compute. "
    "As nations delve into AI sovereignty, governments are funding GPU clusters.\n\n"
    "## Key pillars\n\n"
    "Key pillars driving this foundational transformation include:\n\n"
    "- The deployment of sovereign GPU clusters in three regions.\n"
    "- The adoption of shared data platforms by 40% of ministries [3].\n"
    "1. Moreover, a numbered item stays numbered.\n\n"
    '> "Compute is the new electricity," an official said in 2024.\n\n'
    "```\nleverage = 1  # code is never rewritten\n```\n\n"
    "| Year | GPUs |\n| --- | --- |\n| 2024 | 18,000 |\n"
)


def _shape(text: str) -> list[tuple[str, str]]:
    return [(b.kind, b.prefix) for b in blocks(text)]


@pytest.mark.parametrize("persona", PERSONAS)
def test_markdown_structure_is_kept_exactly(persona: str) -> None:
    result = rewrite(MARKDOWN, persona)  # type: ignore[arg-type]
    assert _shape(result.text) == _shape(MARKDOWN), "same blocks, markers and blank lines"
    assert result.text.count("\n") == MARKDOWN.count("\n")
    for verbatim in (
        '> "Compute is the new electricity," an official said in 2024.',
        "```\nleverage = 1  # code is never rewritten\n```",
        "| 2024 | 18,000 |",
        "# Sovereign AI in India",
    ):
        assert verbatim in result.text
    assert fact_lock(MARKDOWN, result.text).missing == ()


def test_templated_openers_are_removed_or_restructured() -> None:
    text = rewrite(MARKDOWN, "journalist").text
    assert "In today's" not in text and "delve" not in text
    assert "India is building its own compute. Nations examine AI sovereignty. Governments are" in text
    assert "This core transformation rests on:" in text
    assert "- Deploying sovereign GPU clusters in three regions." in text
    assert "- Adopting shared data platforms by 40% of ministries [3]." in text
    assert "1. A numbered item stays numbered." in text


def test_inverted_not_only_becomes_two_sentences() -> None:
    text = "Not only does the new policy cut costs by 12%, but it also improves uptime."
    assert rewrite(text).text == "The new policy cuts costs by 12%. It also improves uptime."
    assert (
        rewrite("Not only is it cheaper, but it is also faster.").text == "It is cheaper. It is also faster."
    )
    unsure = "Not only is the old system slow, but it is also costly."
    assert rewrite(unsure).text == unsure, "left alone when the subject cannot be found safely"


def test_noun_phrase_items_with_a_verb_are_left_alone() -> None:
    item = "- The adoption of cloud tools grew 20% in 2025.\n"
    assert rewrite(item).text == item


def test_single_line_breaks_between_sentences_are_kept() -> None:
    text = "First line ends here.\nSecond line starts a paragraph.\nThird line is wrapped\nmid sentence."
    result = rewrite(text)
    expected = "First line ends here.\nSecond line starts a paragraph.\nThird line is wrapped mid sentence."
    assert result.text == expected
    assert analyze(text).paragraphs == 3


def test_changes_are_listed_with_their_rules() -> None:
    result = rewrite(MARKDOWN, "journalist")
    rules = {rule for change in result.changes for rule in change.rules}
    assert {"opener", "stock phrase", "noun phrase to action"} <= rules
    assert all(change.accepted for change in result.changes)
    assert result.changed_sentences == len(result.changes)


def test_vocabulary_diversity_is_a_share_between_zero_and_one() -> None:
    long_text = " ".join(f"word{n % 30} filler" for n in range(200))
    assert 0 < analyze(long_text).vocabulary_mattr <= 1


def test_each_voice_has_its_own_vocabulary() -> None:
    text = "We don't think it's basically a very big problem, and approximately 30 individuals agree."
    assert rewrite(text, "academic").text == (
        "We do not think it is basically a very large problem, and approximately 30 individuals agree."
    )
    assert (
        rewrite(text, "executive").text
        == "We don't think it's a big problem, and about 30 individuals agree."
    )
    assert rewrite(text, "journalist").text == (
        "We don't think it's basically a very big problem, and about 30 people agree."
    )
    assert (
        rewrite(text, "technical").text
        == "We don't think it's a big problem, and about 30 individuals agree."
    )


def test_quoted_words_are_not_edited_but_the_rest_of_the_sentence_is() -> None:
    text = 'Moreover, the minister said "we leverage robust tools" on Monday.'
    assert rewrite(text, "journalist").text == 'The minister said "we leverage robust tools" on Monday.'


def test_rhythm_changes_only_raise_sentence_length_variation(monkeypatch: pytest.MonkeyPatch) -> None:
    text = MARKDOWN + "\n" + BOILERPLATE + "\n\n" + UNIFORM
    with_rhythm = {p: analyze(rewrite(text, p).text).sentence_length_cv for p in PERSONAS}
    monkeypatch.setattr(style, "_rhythm", lambda parts, persona: (parts, []))
    for persona in PERSONAS:
        assert with_rhythm[persona] >= analyze(rewrite(text, persona).text).sentence_length_cv, persona


def test_uniform_short_sentences_are_joined_when_that_varies_the_rhythm() -> None:
    text = "Costs fell in May. It surprised staff. Sales rose in June. They beat targets."
    result = rewrite(text, "journalist")
    assert result.text.startswith("Costs fell in May, and it surprised staff.")
    assert analyze(result.text).sentence_length_cv > analyze(text).sentence_length_cv
    assert [c.rules for c in result.changes] == [("rhythm",)]

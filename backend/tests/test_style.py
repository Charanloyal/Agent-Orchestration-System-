"""Writing Style Studio: metrics are computed exactly, and a rewrite never changes a fact."""

import pytest

from app.services.style import PERSONAS, analyze, fact_lock, facts, rewrite, stock_phrases

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

"""The research data pipeline (ADR 0031): real open sources instead of the test provider,
sentence-aware passages, short documents whole, re-indexing, and no mid-word cuts."""

import uuid
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import EvidenceRef, EvidenceView
from app.agents.llm_researcher import LlmResearcher
from app.agents.llm_writer_reviewer import _refs, select_passages
from app.config import Settings
from app.contracts import PlanTask
from app.contracts.common import sha256_hex
from app.db.models import EvidencePassage, Role, Source, Upload, UploadChunk, User, Workspace
from app.db.session import get_sessionmaker
from app.providers.open_search import OpenWebSearch, curated_hits, is_relevant, keywords
from app.services.uploads import search_chunks, with_short_documents_whole
from app.tools.chunking import PASSAGE_MAX_CHARS, clip, sentences, split_passages
from app.workers.runner import build_search
from app.workflow.errors import TransientError
from app.workflow.graph import load_evidence
from tests.conftest import LoggedIn
from tests.test_uploads import upload

RESUME = (
    "SKILLS\nPython, Go, Rust, Kubernetes\n\n"
    "PROJECTS\n"
    + " ".join(
        f"RaftKV milestone {n}: a replicated key-value store with CI fault-injection tests across "
        f"network partitions, leader changes and disk stalls, reaching {n}0,000 writes per second."
        for n in range(1, 16)
    )
    + "\n\nEXPERIENCE\nTechnex, IIT (BHU) Varanasi. Machine Learning Intern. Trained 5 M parameter models "
    "for document ranking.\n\nEDUCATION\nB.Tech in Computer Science, 2027."
)


# --- chunking -------------------------------------------------------------------------------


def test_passages_end_on_sentence_or_line_boundaries_and_lose_nothing() -> None:
    passages = split_passages(RESUME, limit=None)
    assert len(passages) > 1
    assert all(len(p) <= PASSAGE_MAX_CHARS for p in passages)
    for passage in passages:
        assert passage.rstrip()[-1] in ".!?:,0123456789sTSOGLNE" or passage.endswith("Kubernetes"), passage[
            -40:
        ]
        assert not passage.endswith(("fault-injection t", "Trained 5 M"))
    rebuilt = " ".join(" ".join(p.split()) for p in passages)
    for sentence in sentences(" ".join(RESUME.split())):
        assert sentence in rebuilt, f"lost: {sentence[:60]}"


def test_only_a_single_over_long_sentence_is_cut_and_then_at_a_word_boundary() -> None:
    sentence = " ".join(["word"] * 1200) + "."
    passages = split_passages(sentence, limit=None)
    assert len(passages) >= 2 and all(len(p) <= PASSAGE_MAX_CHARS for p in passages)
    assert all(p.split()[-1].strip(".") == "word" for p in passages)


def test_pdf_line_breaks_and_hyphenation_are_normalised() -> None:
    text = "Fault-injec-\ntion tests   ran.\r\n\r\n\r\nNext   paragraph."
    assert split_passages(text) == ["Fault-injection tests ran.\n\nNext paragraph."]


def test_abbreviations_and_quotes_do_not_end_sentences() -> None:
    assert sentences('Dr. Rao said "it works." Then e.g. Raft held. Done!') == [
        'Dr. Rao said "it works."',
        "Then e.g. Raft held.",
        "Done!",
    ]


def test_writer_passages_are_whole_or_clipped_at_a_sentence() -> None:
    long = " ".join(f"Sentence number {n} describes a measured result." for n in range(120))
    item = EvidenceView("e1", "s1", "t1", "Doc", None, None, long)
    refs, _ = _refs([item])
    assert refs[0].text.endswith("result.") and len(refs[0].text) <= PASSAGE_MAX_CHARS
    short = EvidenceView("e2", "s1", "t1", "Doc", None, None, RESUME[:1500])
    assert _refs([short])[0][0].text == RESUME[:1500], "passages within the limit are never cut"
    assert clip("One. Two.", 5) == "One."


# --- uploads --------------------------------------------------------------------------------


@pytest.fixture
def team(make_user: Callable[..., User], make_workspace: Callable[..., Workspace]) -> dict[str, Any]:
    analyst = make_user("Ana")
    return {"analyst": analyst, "home": make_workspace("Home", {analyst: Role.ANALYST})}


def test_a_short_document_is_returned_whole_and_in_order(
    client: TestClient, db: Session, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    response = upload(client, login(team["analyst"]), team["home"], "resume.txt", RESUME.encode())
    assert response.status_code == 201, response.text
    upload_id = uuid.UUID(response.json()["id"])
    hits = search_chunks(db, team["home"].id, "Technex intern", match_any=True)
    assert 0 < len(hits) < response.json()["chunks"], "full-text search alone finds only some passages"
    whole = with_short_documents_whole(db, team["home"].id, hits)
    assert [h.chunk_index for h in whole] == list(range(response.json()["chunks"]))
    joined = " ".join(h.text for h in whole)
    assert "SKILLS" in joined and "EDUCATION" in joined and "Trained 5 M parameter models" in joined
    long_hits = with_short_documents_whole(db, team["home"].id, hits, max_passages=1)
    assert {h.upload_id for h in long_hits} == {upload_id} and len(long_hits) == len(hits)


def test_reindex_rebuilds_old_mid_sentence_passages(
    client: TestClient, db: Session, team: dict[str, Any], login: Callable[[User], LoggedIn]
) -> None:
    analyst = login(team["analyst"])
    upload_id = uuid.UUID(upload(client, analyst, team["home"], "resume.txt", RESUME.encode()).json()["id"])
    # Simulate the old chunker: hard cuts in the middle of sentences, on one page.
    for chunk in db.scalars(select(UploadChunk).where(UploadChunk.upload_id == upload_id)).all():
        db.delete(chunk)
    db.flush()
    flat = " ".join(RESUME.split())
    cuts = [flat[i : i + 700].strip() for i in range(0, len(flat), 700)]
    for index, text in enumerate(cuts):
        db.add(
            UploadChunk(
                upload_id=upload_id,
                chunk_index=index,
                workspace_id=team["home"].id,
                locator=f"page 1, passage {index + 1}",
                text=text,
            )
        )
    db.commit()

    response = client.post(f"/api/v1/workspaces/{team['home'].id}/uploads/reindex", headers=analyst.headers)
    assert response.status_code == 200, response.text
    assert response.json()["documents"] == 1 and response.json()["passages_before"] == len(cuts)
    db.expire_all()
    rebuilt = db.scalars(
        select(UploadChunk).where(UploadChunk.upload_id == upload_id).order_by(UploadChunk.chunk_index)
    ).all()
    assert all(c.locator and c.locator.startswith("page 1, passage ") for c in rebuilt)
    assert all(c.text.rstrip()[-1] in ".!?" for c in rebuilt[:-1]), [c.text[-30:] for c in rebuilt]
    assert db.get(Upload, upload_id) is not None


# --- open web search ------------------------------------------------------------------------

ARXIV_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1702.08734v1</id>
    <published>2017-02-28T00:00:00Z</published>
    <title>Billion-scale similarity search
      with GPUs</title>
    <summary>Similarity search finds application in specialized database systems
      handling complex data.</summary>
  </entry>
</feed>"""


def fake_web(request: httpx.Request) -> httpx.Response:
    params = dict(request.url.params)
    if request.url.host == "en.wikipedia.org" and params.get("list") == "search":
        return httpx.Response(200, json={"query": {"search": [{"title": "FAISS"}]}})
    if request.url.host == "en.wikipedia.org":
        extract = "FAISS is a library for efficient similarity search. " * 10 + "\n== References ==\nx"
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": {
                        "1": {
                            "title": "FAISS",
                            "extract": extract,
                            "revisions": [{"timestamp": "2026-10-01T00:00:00Z"}],
                        }
                    }
                }
            },
        )
    if request.url.host == "export.arxiv.org":
        return httpx.Response(200, text=ARXIV_FEED)
    return httpx.Response(404)


def test_open_search_returns_real_source_text_from_wikipedia_and_arxiv() -> None:
    search = OpenWebSearch(client=httpx.Client(transport=httpx.MockTransport(fake_web)))
    response = search.search(
        "Compare FAISS GPU similarity search", max_results=4, allowed_domains=[], blocked_domains=[]
    )
    assert [h.url for h in response.hits] == [
        "https://github.com/facebookresearch/faiss/wiki",
        "https://en.wikipedia.org/wiki/FAISS",
        "https://arxiv.org/abs/1702.08734v1",
    ]
    docs, wiki, paper = response.hits
    assert docs.content is None, "curated documentation is fetched live, never stored text"
    assert wiki.title == "FAISS (Wikipedia)" and wiki.published_on == "2026-10-01"
    assert wiki.content and "References" not in wiki.content
    assert paper.title == "Billion-scale similarity search with GPUs (arXiv)"
    assert paper.content and paper.content.endswith("handling complex data.")
    for hit in response.hits:
        assert "synthetic" not in (hit.content or "").lower() and "no real-world facts" not in (
            hit.content or ""
        )


def test_open_search_respects_the_domain_policy_and_skips_an_outage() -> None:
    search = OpenWebSearch(client=httpx.Client(transport=httpx.MockTransport(fake_web)))
    only_arxiv = search.search(
        "similarity search", max_results=3, allowed_domains=["arxiv.org"], blocked_domains=[]
    )
    assert [h.url.split("/")[2] for h in only_arxiv.hits if h.url] == ["arxiv.org"]
    down = OpenWebSearch(client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))))
    outage = down.search(
        "Bloom filter false positives", max_results=3, allowed_domains=[], blocked_domains=[]
    )
    assert outage.hits == [], "a source that is down is skipped, never a transient error that fails the run"
    faiss = down.search("FAISS", max_results=3, allowed_domains=[], blocked_domains=[])
    assert [h.url for h in faiss.hits] == ["https://github.com/facebookresearch/faiss/wiki"]


def test_auto_search_without_a_key_uses_open_sources() -> None:
    settings = Settings(_env_file=None, search_provider="auto")  # type: ignore[call-arg]
    assert settings.search_provider == "open"
    assert isinstance(build_search(settings), OpenWebSearch)
    assert keywords("How does FAISS compare with Qdrant for vector search?") == [
        "FAISS",
        "Qdrant",
        "vector",
        "search",
    ]


# --- relevance (ADR 0033) -------------------------------------------------------------------

BREAKER_QUESTION = (
    "How should the gateway implement the circuit breaker pattern for building resilient "
    "handling of transient upstream errors?"
)
OFF_TOPIC_PAGES = {
    "Sick building syndrome": "Sick building syndrome is a condition in which occupants of a building "
    "experience acute health effects that seem linked to time spent in it. ",
    "Pattern (sewing)": "In sewing and fashion design, a pattern is the template from which the parts "
    "of a garment are traced onto fabric before being cut out. ",
    "Pornography": "Pornography is sexually explicit material; one gateway site was studied. ",
    "Circuit breaker design pattern": "Circuit breaker is a design pattern used in software development "
    "to detect failures and stop a failing upstream call from being retried constantly. ",
}


def polluted_web(request: httpx.Request) -> httpx.Response:
    params = dict(request.url.params)
    if request.url.host == "en.wikipedia.org" and params.get("list") == "search":
        return httpx.Response(200, json={"query": {"search": [{"title": t} for t in OFF_TOPIC_PAGES]}})
    if request.url.host == "en.wikipedia.org":
        title = params["titles"]
        page = {"title": title, "extract": OFF_TOPIC_PAGES[title] * 4, "revisions": []}
        return httpx.Response(200, json={"query": {"pages": {"1": page}}})
    if request.url.host == "export.arxiv.org":
        return httpx.Response(200, text='<feed xmlns="http://www.w3.org/2005/Atom"></feed>')
    return httpx.Response(404)


def test_off_topic_and_adult_pages_never_reach_the_evidence() -> None:
    search = OpenWebSearch(client=httpx.Client(transport=httpx.MockTransport(polluted_web)))
    response = search.search(BREAKER_QUESTION, max_results=6, allowed_domains=[], blocked_domains=[])
    titles = [h.title for h in response.hits]
    assert titles == ["CircuitBreaker (Martin Fowler)", "Circuit breaker design pattern (Wikipedia)"]
    assert response.hits[0].url == "https://martinfowler.com/bliki/CircuitBreaker.html"


def test_relevance_needs_a_distinctive_word_not_only_generic_ones() -> None:
    assert not is_relevant(
        "transient errors in a rate limit gateway",
        "GWTC-5.0: a catalog of gravitational-wave transient sources (arXiv)",
        "We report transient signals observed by the detector network.",
    )
    assert is_relevant(
        "token bucket rate limit in Redis",
        "Rate limiting (Wikipedia)",
        "A token bucket allows bursts while enforcing an average rate limit.",
    )
    assert is_relevant("Raft", "Raft (algorithm) (Wikipedia)", "Raft is a consensus algorithm.")


def test_curated_documentation_matches_whole_terms_and_respects_the_policy() -> None:
    assert [h.url for h in curated_hits("Raft leader election versus Paxos")] == ["https://raft.github.io/"]
    assert curated_hits("assess the draft report") == [], "no match inside other words"
    search = OpenWebSearch(client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))))
    blocked = search.search(
        "Raft log replication", max_results=3, allowed_domains=[], blocked_domains=["raft.github.io"]
    )
    assert blocked.hits == []


def test_writer_sees_every_uploaded_passage_before_web_passages() -> None:
    upload_passages = [
        EvidenceView(f"u{i}", "upl-cv", "t1", "CV", None, None, f"passage {i}", "upload") for i in range(1, 5)
    ]
    web = [
        EvidenceView(f"w{t}{i}", f"web-{t}{i}", t, "Doc", "https://example.com", None, "text")
        for t in ("t1", "t2", "t3")
        for i in range(15)
    ]
    plan = SimpleNamespace(tasks=[SimpleNamespace(task_id=t) for t in ("t1", "t2", "t3")])
    chosen = select_passages(plan, web[:20] + upload_passages + web[20:])  # type: ignore[arg-type]
    assert [e.evidence_id for e in chosen[:4]] == ["u1", "u2", "u3", "u4"]
    assert len(chosen) == 36 and {e.task_id for e in chosen[4:]} == {"t1", "t2", "t3"}


def test_evidence_is_loaded_uploads_first_in_document_order(
    db: Session,
    make_user: Callable[..., User],
    make_workspace: Callable[..., Workspace],
    make_run: Callable[..., uuid.UUID],
) -> None:
    from datetime import UTC, datetime, timedelta

    user = make_user("Owner")
    workspace = make_workspace("Evidence order", {user: Role.ADMIN})
    run_id = make_run(workspace, user)
    now = datetime.now(UTC)
    for source_id, kind, at in (("web-1", "web", now - timedelta(minutes=5)), ("upl-cv", "upload", now)):
        db.add(
            Source(
                run_id=run_id,
                source_id=source_id,
                workspace_id=workspace.id,
                kind=kind,
                url="https://example.com" if kind == "web" else None,
                title=source_id,
                retrieved_at=at,
                fetch_status="fetched",
            )
        )
    db.flush()
    rows = [
        ("0-web", "web-1", None, "Web passage."),
        ("9-cv1", "upl-cv", "page 1, passage 1", "Header and summary."),
        ("1-cv10", "upl-cv", "page 1, passage 10", "Last project."),
        ("5-cv2", "upl-cv", "page 1, passage 2", "Skills and internships."),
    ]
    for evidence_id, source_id, locator, text in rows:
        db.add(
            EvidencePassage(
                run_id=run_id,
                evidence_id=evidence_id,
                workspace_id=workspace.id,
                source_id=source_id,
                task_id="t1",
                locator=locator,
                text=text,
                text_sha256=sha256_hex(text),
                fencing_token=1,
            )
        )
    db.commit()
    loaded = load_evidence(SimpleNamespace(sm=get_sessionmaker(), run_id=run_id))  # type: ignore[arg-type]
    assert [e.evidence_id for e in loaded] == ["9-cv1", "5-cv2", "1-cv10", "0-web"]
    assert [e.kind for e in loaded] == ["upload", "upload", "upload", "web"]


class EarlierAttemptTools:
    def __init__(self) -> None:
        self.searches = 0

    def collected(self) -> list[tuple[EvidenceRef, str]]:
        return [
            (
                EvidenceRef("ev-1", "s1", "Raft keeps a replicated log. Leaders are elected."),
                "Raft (Wikipedia)",
            )
        ]

    def search(self, query: str) -> list[Any]:
        self.searches += 1
        return []

    def search_uploads(self, query: str) -> list[Any]:
        self.searches += 1
        return []

    def collect(self, hit: Any) -> list[EvidenceRef]:
        raise AssertionError("nothing is collected twice")


class AlwaysRateLimited:
    name, model = "google-gemini", "gemini-4-hydrogen"

    def complete(self, **_: Any) -> Any:
        raise TransientError("every Gemini model was unavailable: HTTP 429")


def test_a_retried_task_reuses_its_passages_and_quotes_them_when_no_model_answers() -> None:
    task = PlanTask(
        task_id="t3",
        question="How does Raft elect a leader?",
        depends_on=[],
        tools=["web_search"],
        expected_evidence="docs",
        section_ids=["summary"],
    )
    tools = EarlierAttemptTools()
    researcher = LlmResearcher(AlwaysRateLimited(), fallback=True)  # type: ignore[arg-type]
    call = researcher.research(SimpleNamespace(topic="Raft"), task, tools)  # type: ignore[arg-type]
    assert tools.searches == 0
    assert [f.statement for f in call.output.findings] == ['Raft (Wikipedia): "Raft keeps a replicated log."']
    assert call.output.evidence_ids == ["ev-1"] and call.generation["fallback_reason"].endswith("HTTP 429")
    strict = LlmResearcher(AlwaysRateLimited())  # type: ignore[arg-type]
    with pytest.raises(TransientError):
        strict.research(SimpleNamespace(topic="Raft"), task, EarlierAttemptTools())  # type: ignore[arg-type]

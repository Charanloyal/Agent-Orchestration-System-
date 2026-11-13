"""The research data pipeline (ADR 0031): real open sources instead of the test provider,
sentence-aware passages, short documents whole, re-indexing, and no mid-word cuts."""

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import EvidenceView
from app.agents.llm_writer_reviewer import _refs
from app.config import Settings
from app.db.models import Role, Upload, UploadChunk, User, Workspace
from app.providers.open_search import OpenWebSearch, keywords
from app.services.uploads import search_chunks, with_short_documents_whole
from app.tools.chunking import PASSAGE_MAX_CHARS, clip, sentences, split_passages
from app.workers.runner import build_search
from app.workflow.errors import TransientError
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
        "https://en.wikipedia.org/wiki/FAISS",
        "https://arxiv.org/abs/1702.08734v1",
    ]
    wiki, paper = response.hits
    assert wiki.title == "FAISS (Wikipedia)" and wiki.published_on == "2026-10-01"
    assert wiki.content and "References" not in wiki.content
    assert paper.title == "Billion-scale similarity search with GPUs (arXiv)"
    assert paper.content and paper.content.endswith("handling complex data.")
    for hit in response.hits:
        assert "synthetic" not in (hit.content or "").lower() and "no real-world facts" not in (
            hit.content or ""
        )


def test_open_search_respects_the_domain_policy_and_reports_an_outage() -> None:
    search = OpenWebSearch(client=httpx.Client(transport=httpx.MockTransport(fake_web)))
    only_arxiv = search.search("FAISS", max_results=3, allowed_domains=["arxiv.org"], blocked_domains=[])
    assert [h.url.split("/")[2] for h in only_arxiv.hits if h.url] == ["arxiv.org"]
    down = OpenWebSearch(client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))))
    with pytest.raises(TransientError):
        down.search("FAISS", max_results=3, allowed_domains=[], blocked_domains=[])


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

"""Opt-in live smoke tests against the configured LLM provider. NOT run by default or in CI.

Run only with an approved budget (ADR 0005):
    $env:AOS_LIVE_TESTS = "1"; python -m pytest -m live -s tests/live
One planner call with a small brief costs a few thousand tokens.
"""

import os

import pytest

from app.agents.llm_planner import LlmPlanner
from app.config import get_settings
from app.contracts import Brief
from app.providers.llm import OpenAICompatibleLlm

pytestmark = pytest.mark.live

LIVE = os.environ.get("AOS_LIVE_TESTS") == "1"


@pytest.mark.skipif(not LIVE, reason="live provider tests need AOS_LIVE_TESTS=1 and an approved budget")
def test_live_planner_returns_a_valid_plan() -> None:
    settings = get_settings()
    if settings.llm_api_key is None and settings.llm_base_url is None:
        pytest.skip("no LLM provider configured (AOS_LLM_API_KEY or AOS_LLM_BASE_URL)")
    brief = Brief.model_validate(
        {
            "topic": "Compare two open-source full-text search engines for a small team",
            "audience": "Engineering manager",
            "research_questions": [
                "Which engines can be self-hosted?",
                "What are their documented limitations?",
            ],
            "source_policy": {"allowed_source_types": ["public_web", "vendor_docs"]},
            "budget": {"max_estimated_cost": "0.50"},
            "limits": {"max_tasks": 4},
        }
    )
    call = LlmPlanner(OpenAICompatibleLlm(settings), max_output_tokens=1500).plan(
        brief, version=1, feedback=None
    )
    print(
        f"\nlive planner: model={call.generation['model']} attempts={call.attempts} "
        f"tokens in/out={call.generation['input_tokens']}/{call.generation['output_tokens']}"
    )
    assert 1 <= len(call.output.tasks) <= 4

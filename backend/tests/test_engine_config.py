"""Model and search keys from a provider's own variable, and `auto` modes (deploy-render.md §6)."""

import pytest

from app.config import Settings

KEY_VARIABLES = ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "TAVILY_API_KEY")
AOS_VARIABLES = (
    "AOS_LLM_API_KEY",
    "AOS_LLM_BASE_URL",
    "AOS_LLM_MODEL",
    "AOS_AGENT_MODE",
    "AOS_SEARCH_PROVIDER",
)


@pytest.fixture(autouse=True)
def _no_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (*KEY_VARIABLES, *AOS_VARIABLES):
        monkeypatch.delenv(variable, raising=False)


def settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_auto_without_keys_runs_the_demo_agents() -> None:
    s = settings(agent_mode="auto", search_provider="auto")
    assert (s.agent_mode, s.search_provider, s.llm_api_key) == ("fake", "fake", None)


@pytest.mark.parametrize(
    ("variable", "base_url", "model"),
    [
        ("GROQ_API_KEY", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
        ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash"),
        ("OPENAI_API_KEY", None, "gpt-4o-mini"),
    ],
)
def test_a_provider_key_configures_its_endpoint_and_model(
    monkeypatch: pytest.MonkeyPatch, variable: str, base_url: str | None, model: str
) -> None:
    monkeypatch.setenv(variable, "secret-value")
    s = settings(agent_mode="auto")
    assert s.agent_mode == "llm"
    assert s.llm_api_key is not None and s.llm_api_key.get_secret_value() == "secret-value"
    assert (s.llm_base_url, s.llm_model) == (base_url, model)
    assert "secret-value" not in repr(s), "the key never appears in logs or reprs"


def test_explicit_settings_win_over_provider_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "groq")
    local = "http://127.0.0.1:11434/v1"
    s = settings(agent_mode="auto", llm_api_key="own", llm_base_url=local, llm_model="llama3.1")
    assert s.llm_api_key is not None and s.llm_api_key.get_secret_value() == "own"
    assert (s.llm_base_url, s.llm_model) == (local, "llama3.1")
    monkeypatch.setenv("AOS_LLM_MODEL", "llama-3.1-8b-instant")
    assert settings(agent_mode="auto").llm_model == "llama-3.1-8b-instant", "AOS_LLM_MODEL picks the model"


def test_a_key_alone_does_not_switch_the_demo_agents_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gemini")
    assert settings().agent_mode == "fake", "only agent_mode=auto or llm uses a model"


def test_auto_search_uses_tavily_when_its_key_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "tvly")
    s = settings(search_provider="auto")
    assert s.search_provider == "tavily"
    assert s.tavily_api_key is not None and s.tavily_api_key.get_secret_value() == "tvly"

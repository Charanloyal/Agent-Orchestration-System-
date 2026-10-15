"""Server-side tool policy derived from the brief (never from model output)."""

from app.contracts import Brief, PlanPolicy
from app.contracts.plan import ToolName


def allowed_tools(brief: Brief) -> frozenset[ToolName]:
    types = set(brief.source_policy.allowed_source_types)
    tools: set[ToolName] = set()
    if types & {"public_web", "vendor_docs"}:
        tools |= {"web_search", "fetch_url"}
    if "uploaded_documents" in types:
        tools.add("search_uploads")
    return frozenset(tools)


def plan_policy_for(brief: Brief) -> PlanPolicy:
    return PlanPolicy(allowed_tools=allowed_tools(brief), max_tasks=brief.limits.max_tasks)

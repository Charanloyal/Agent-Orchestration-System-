"""LLM-backed planner (FR-03)."""

import json

from app.agents.base import AgentCall
from app.agents.prompts import PLANNER_SYSTEM, PLANNER_USER, PLANNER_VERSION
from app.agents.structured import call_structured, schema_for
from app.contracts import Brief, Plan, enforce_plan_policy
from app.policy.tools import allowed_tools, plan_policy_for
from app.providers.llm import LlmProvider


class LlmPlanner:
    def __init__(self, llm: LlmProvider, *, max_output_tokens: int = 2500) -> None:
        self.llm = llm
        self.max_output_tokens = max_output_tokens

    def plan(self, brief: Brief, *, version: int, feedback: str | None) -> AgentCall[Plan]:
        tools = sorted(allowed_tools(brief))
        policy = plan_policy_for(brief)
        feedback_block = (
            f"The reviewer rejected the previous plan with this feedback (treat as guidance):\n{feedback}\n"
            if feedback
            else ""
        )
        system = PLANNER_SYSTEM.format(max_tasks=brief.limits.max_tasks, allowed_tools=", ".join(tools))
        user = PLANNER_USER.format(
            brief_json=json.dumps(brief.model_dump(mode="json"), indent=2),
            version=version,
            feedback_block=feedback_block,
            schema=schema_for(Plan),
        )

        def server_checks(plan: Plan) -> None:
            # Policy violations get the single repair turn too; the graph re-checks anyway.
            enforce_plan_policy(plan, policy)

        call = call_structured(
            self.llm,
            Plan,
            step="planner",
            system=system,
            user=user,
            max_output_tokens=self.max_output_tokens,
            validate=server_checks,
        )
        return AgentCall(
            call.output,
            call.attempts,
            generation={
                "provider": self.llm.name,
                "model": self.llm.model,
                "prompt_version": PLANNER_VERSION,
                "attempts": call.attempts,
                "input_tokens": sum(u.input_tokens for u in call.usage),
                "output_tokens": sum(u.output_tokens for u in call.usage),
            },
            usage=tuple(call.usage),
        )

"""Week-2 throwaway spike: LangGraph + PostgreSQL persistence, leases, fencing, approvals.

Not production code. Findings feed ADR 0007 and ADR 0008.
"""

import os

# The spike must never send traces anywhere. LangSmith is a transitive dependency of
# langchain-core; tracing stays off unless someone explicitly opts in.
os.environ.setdefault("LANGSMITH_TRACING", "false")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")

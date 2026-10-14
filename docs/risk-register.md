# Risk register

Likelihood and impact use H/M/L. **Owner** is the project lead unless stated otherwise. Review
this register at the end of every milestone.

| ID | Risk | L | I | Mitigation | Trigger / early signal | Status |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | Overengineering: building platform features before the workflow is proven | M | H | One workflow, one deployment, one model and one search adapter; milestone-by-milestone delivery | A milestone adds infrastructure no test needs | Open |
| R2 | Unsupported or fabricated claims reach an approved report | M | H | Evidence-ID contracts, `validate_citations`, reviewer, abstention, human approval of the exact version | Evidence-support sample < 90% | Open |
| R3 | Unbounded spend | M | H | Fake providers by default; reservations before calls; bounded loops and retries; spending ceiling ([ADR 0005](decisions/0005-spending-ceiling.md)) | Reconciled cost exceeds reservation; ceiling UNDECIDED at Week 5 | Open: ceiling undecided |
| R4 | LangGraph checkpoint fencing relies on a private API (`PostgresSaver._cursor`) | M | H | Pinned versions; spike S3 test plus negative control must pass on every upgrade; fallback is a single-writer design ([ADR 0007](decisions/0007-checkpoint-persistence-and-fencing.md)) | Upgrade changes `_cursor`, or S3 fails | Open: accepted with guard |
| R5 | Brittle research: sources change, block fetching or disagree | H | M | Record fetch failures, retrieval and publication dates, and conflicts; show conflicts instead of resolving them silently | Rising fetch-failure rate in the run timeline | Open |
| R6 | Evaluation leakage or invalid comparison | M | H | Separate dev and held-out sets; held-out procedure; matched baseline budgets; blind scoring | Held-out cases edited after results; baseline gets different tools | Open |
| R7 | Data exposure across workspaces or to providers | L | H | Server-side authorization on every path; public or synthetic data only in the pilot; provider retention review | Any cross-workspace test failure | Open |
| R8 | Problem hypothesis is wrong (users don't value this) | M | H | 3–5 interviews before Week 3; decision rule in the [interview guide](product/interview-guide.md) | Fewer than 3/5 confirm the bottleneck | Open: interviews NOT DONE |
| R9 | Multi-agent design is no better than a single agent | M | M | Baseline and reviewer ablation; simplify if not better | Week-11 results | Open |
| R10 | Corporate network blocks package installs (NTLM proxy) | H | M | Use an approved mirror; temporary localhost relay used once with user approval | `407 Proxy Authentication Required` | Mitigated for now; ask IT for a mirror |
| R11 | Unverified local PostgreSQL binaries (no published checksum or signature) | L | M | Local development only, bound to 127.0.0.1; replace with a verified or managed PostgreSQL for shared environments | Any non-local use | Open: accepted locally |
| R12 | Very new runtime versions (Python 3.14, TypeScript 7, Vite 8) break third-party packages | M | M | Exact pins; warnings as errors; record targeted upstream warning filters | Deprecation warnings from dependencies (already one: langsmith) | Open |
| R13 | Solo-developer capacity: 16 weeks at 20–30 h/week is optimistic | M | M | Follow the PRD 12-week cut list; protect the P0 boundary | Two consecutive milestones slip | Open |

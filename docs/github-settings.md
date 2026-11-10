# GitHub repository settings (owner, in the browser)

These cannot be set from git. Signed in as the repository owner:

## About (repository home page, gear icon next to "About")

- **Description:** `Multi-agent research with human approval: planner, parallel researchers,
  writer and reviewer agents produce cited reports; FastAPI, LangGraph, React, PostgreSQL.`
- **Website:** the Render URL once the deployment is verified (until then, leave it empty).
- **Topics:** `multi-agent`, `llm`, `langgraph`, `human-in-the-loop`, `fastapi`, `react`,
  `postgresql`, `evaluation`, `rag`, `ai-agents`
- Tick **Releases**; untick **Packages** and **Deployments** if unused.

## License

`LICENSE` (MIT) is in the repository root; GitHub detects it after the merge to `main`.

## Release

After the owner approves: **Releases > Draft a new release**, tag `v1.0.0` on `main`, title
"v1.0.0", body from [release-notes-v1.0.0.md](release-notes-v1.0.0.md) with the PENDING lines
filled in from evidence.

## Branch protection (recommended)

**Settings > Branches > Add rule** for `main`: require a pull request and the CI checks
`backend`, `frontend`, `e2e`, `containers`, `deploy-image`, `spike` to pass. Render deploys
`main` only after checks pass (`autoDeployTrigger: checksPass`), so this keeps `main`
deployable.

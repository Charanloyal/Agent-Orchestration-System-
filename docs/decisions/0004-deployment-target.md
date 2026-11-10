# 0004: Deployment target

- **Status:** Superseded (2026-11-10) by [ADR 0018](0018-production-image-render-hardening.md)
  and [ADR 0023](0023-deploy-topologies-and-ci-proof.md). Originally accepted 2026-10-14 by the
  project lead.
- **Decision (original):** **local demo only**, production-like. Docker Compose plus a native run, a deployment guide, runbooks, and a local backup/restore and rollback drill. No paid cloud. Option A remains the documented path for a future hosted pilot.
- **Date:** 2026-10-14

> **Superseded.** The project now deploys to Render (option B below): ADR 0018 defines the
> single-origin production image and its hardening, and ADR 0023 the topologies, with the
> hybrid blueprint (one free web service running API and worker, plus a paid Postgres,
> `singapore`) chosen by the owner. Local Docker Compose remains the development and
> rehearsal environment. The rest of this record is kept as written for history.

## Context

PRD §3.1 calls for one cloud container environment with managed PostgreSQL and S3-compatible
object storage, TLS, backups and secrets management. The pilot runs an API, workers and a
static frontend. Kubernetes and multi-region deployment are out of scope.

## Decision criteria

1. Managed PostgreSQL with point-in-time recovery, and a tested restore.
2. Container hosting for the API and for long-running workers (no request-time limits for
   workers).
3. Secret manager, TLS and private networking between services and the database.
4. Egress control for workers, which the SSRF defence depends on (T2 in the threat model).
5. Fit with the model provider (ADR 0002) and any corporate cloud agreement.
6. Predictable cost at pilot scale, within the spending ceiling (ADR 0005).

## Options

| Option | Notes |
| --- | --- |
| A. A managed container service on a major cloud, plus managed PostgreSQL and object storage | Strongest fit for the criteria; check egress controls and minimum costs |
| B. Platform-as-a-service with managed Postgres | Simpler; check worker support, egress control and backup restore |
| C. A single VM running Docker Compose | Cheapest and simplest; backups, TLS and patching become manual work; acceptable for a closed demo only |

## Consequences

Until this is decided, Docker Compose for local development (Week 3) is the only environment.
Nothing is deployed publicly. The current scaffold is unauthenticated.

**Decision owner:** project lead. **Revisit by:** before Week 10.

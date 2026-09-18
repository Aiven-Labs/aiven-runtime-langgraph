# Validation

## Local checks — 18 September 2026

- Eight tests passed using Python 3.12, LangGraph 1.2.11 and the pinned dependencies.
- Tested draft creation, revision, approval and reopening state with a rebuilt graph and shared in-memory checkpointer.
- Tested stale-review rejection and rejection of changes to completed runs.
- Simulated provider failure, checked secrets are not returned, then successfully continued the saved run.
- Tested login rejection/success, cookie protection, CSRF checks, logout, API key authentication, input validation and login rate limiting.
- Tested strict PostgreSQL TLS configuration, valid CA decoding and missing-configuration failures.
- Tested that excess concurrent executions are rejected before consuming database connections, preserving capacity for checkpoint writes.
- Browser walkthrough passed: login, draft creation, revision, approval, page reload and reopening the saved completed run. Default desktop layout inspected visually.

## Pending

- Dedicated mobile-device layout inspection.
- Container build and local Compose startup (no container engine available in authoring environment).
- Live Aiven Runtime deployment and PostgreSQL schema/checkpoint setup.
- PostgreSQL advisory-lock behaviour under concurrent requests.
- Pausing a run, restarting the Runtime application and resuming from PostgreSQL.
- Real-provider inference with privately supplied credentials.
- Confirming suggested plan sizes and actual pricing.

The functional/API tests use in-memory persistence and do not establish PostgreSQL or process-restart durability. Production always requires PostgreSQL. No Aiven services have been created for this starter yet.

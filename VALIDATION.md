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

## Aiven Runtime — 18 September 2026

Deployed unchanged commit `476cd3818805f68553cd31268e90c47bef0d395b` with Aiven MCP, the root Dockerfile and an explicit PostgreSQL credential integration in AWS Ireland (`aws-eu-west-1`).

| Service | Tested plan | Listed base price/hour |
| --- | --- | --- |
| Runtime | `startup-50-1024`, one replica, 1 GiB | $0.03836 |
| PostgreSQL | `startup-4`, PostgreSQL 16 configured | $0.151 |

Combined listed base price: **$0.18936/hour**, approximately **$4.54/day** while running, before additional charges or account-specific discounts. Prices checked for the test project and region on this date.

Passed:

- Container build, image scan and deployment from the pushed commit.
- PostgreSQL schema setup and application readiness over the configured verified-TLS connection. A separate client also connected with certificate and hostname verification.
- Unauthenticated API calls returned 401. Browser login rejected an incorrect password and accepted the configured password.
- Created a mock draft, requested a revision and retrieved version 2 from PostgreSQL. A stale review checkpoint returned 409.
- Holding the run's PostgreSQL advisory lock from a separate database session caused an approval request to return 409. Five checkpoint records had been saved at that stage.
- Powered the application off and on while version 2 was paused for review. Logs confirmed the old process shut down and a new runtime instance started. The draft, checkpoint ID and pending-review state survived unchanged.
- Resumed the paused run after restart. Two simultaneous approval requests returned one 200 and one 409; the final saved state was complete with version 2 intact.
- Reloaded the browser after restart and reopened the completed run; its session and saved content remained available.

No implementation changes were needed. The completed workshop-announcement run exists only in the test installation; the template does not seed it. Testing used mock mode and made no external model calls.

## Remaining checks

- Dedicated mobile-device layout inspection.
- Container build and local Compose startup (no container engine available in authoring environment).
- Real-provider inference with privately supplied credentials.
- Load testing, production sizing and high availability.
- Console Compose scanner deployment; live testing used MCP and the root Dockerfile.
- Runtime ignored the Dockerfile HEALTHCHECK for OCI format; readiness was checked independently.

The local automated tests use in-memory persistence. The live checks above separately establish PostgreSQL checkpoint persistence across an application restart for this demo. Production always requires PostgreSQL.

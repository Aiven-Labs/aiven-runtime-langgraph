# LangGraph application starter for Aiven Runtime

A starter application built with **LangGraph, FastAPI and Aiven PostgreSQL**, ready to deploy on Aiven Runtime. Includes an editable draft-and-review workflow, a small browser UI, and an authenticated HTTP API.

This repository uses the open-source LangGraph library inside its own Python application. It does not deploy LangSmith Agent Server or its API. Only Runtime and PostgreSQL are needed; no queue broker, object store or external tracing account is required.

## Try the workflow

1. Sign in to the shared demo workspace.
2. Enter a request such as “Write a short announcement for our community workshop.”
3. The graph creates a draft, saves its state to PostgreSQL, and pauses for review.
4. Request a revision with feedback, or approve the draft to finish.
5. Reopen a saved run later, including after an application restart.

**Mock mode is the default.** It produces explicitly labelled, deterministic demo text and makes no model-provider calls. Real mode calls an OpenAI-compatible chat-completions endpoint using your chosen model and private API key. Approving a draft only marks it complete; nothing is sent or published.

```text
Browser / API client --HTTPS--> Runtime :8080
                                  |
                          FastAPI + LangGraph
                                  |
                             verified TLS
                                  |
                           Aiven PostgreSQL
                       run index + checkpoints

Request --> Draft --> Review --> Complete
              ^         |
              +-- Revise+
```

## Local setup

Requires Docker Compose v2 and a running container engine.

1. Copy `.env.example` to `.env`.
2. Run `openssl rand -hex 24` separately for `POSTGRES_PASSWORD`, `APP_PASSWORD`, `SESSION_SECRET` and `APP_API_KEY`. Put the four different values in `.env`. Use a URL-safe PostgreSQL password, or URL-encode it in the connection URI.
3. Run `docker compose up --build -d`.
4. Open <http://localhost:8080> and sign in with `APP_PASSWORD`.

The local port is published only on loopback. Local PostgreSQL uses the private Compose network with TLS disabled. Never set `LOCAL_DEVELOPMENT=true` on Runtime.

`docker compose down` preserves data. `docker compose down -v` permanently deletes local requests, drafts and checkpoints.

## Deploy on Aiven Runtime

1. Commit and push this repository to GitHub so Runtime can access it.
2. In Aiven Console, deploy an application from the repo and scan **compose.aiven.yaml**.
3. Choose a dedicated PostgreSQL service and check the integration maps its connection string to `DATABASE_URL`. PostgreSQL 16 is the reference version; the scanner does not enforce the Compose image tag, so review the version in Console.
4. Add the required variables below before startup. Publish only HTTP port **8080**.
5. Start with **one Runtime replica, one Python worker and 1 GiB RAM** for a small demo. A PostgreSQL `startup-4` plan is a conservative starting point consistent with the 10-connection pool. These are estimates pending live validation, not tested minimums or production sizing. Review free/internal plans and current prices before provisioning.
6. Wait for startup schema setup, then open the generated HTTPS URL and sign in. `/health/ready` checks the database; `/health/live` checks the application process.

For MCP/API deployment, use the root Dockerfile and an `application_service_credential` integration exposing the PostgreSQL connection string as `DATABASE_URL`. The API does not deploy Compose files directly.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Integration-provided PostgreSQL URI with credentials, host, actual port and existing database |
| `PG_CA_CERT_BASE64` | Project CA PEM encoded on one line: `openssl base64 -A -in ca.pem` |
| `APP_PASSWORD` | Shared demo login password, at least 16 characters |
| `SESSION_SECRET` | Independent random signing secret, at least 32 characters; preserve to keep sessions valid |
| `APP_API_KEY` | Independent random API bearer key, at least 32 characters |
| `MODEL_MODE` | `mock` (default) or `openai-compatible` |
| `MODEL_NAME` | Required in real mode: a model ID supported by the chosen endpoint |
| `MODEL_API_KEY` | Required in real mode: provider credential, stored as a Runtime secret |
| `MODEL_BASE_URL` | HTTPS API prefix; defaults to `https://api.openai.com/v1` |

Store credentials as Runtime secrets and keep them out of Git. The wrapper requires PostgreSQL certificate and hostname verification (`sslmode=verify-full`). URI query options are replaced so an incoming URI cannot turn off TLS. Database tables are created at startup; the database itself must already exist and be writable by the supplied account.

Real mode sends the request, previous draft and revision feedback to your configured provider and may incur charges. The provider must support `/chat/completions`, `messages` and `max_tokens`. Responses have a 45-second network timeout and a 1,200-token output cap. No automatic HTTP retries are configured. Saved runs use the current deployment's model configuration when continued.

## HTTP API

Use `Authorization: Bearer $APP_API_KEY` for these endpoints. All API-key holders and signed-in users share the same workspace and can access all runs. This is a single-workspace demo, not a multi-tenant access model.

| Method and path | Purpose |
| --- | --- |
| `POST /api/runs` | Create and execute a draft step; body `{"request":"Write a welcome note"}` |
| `GET /api/runs` | List the newest 50 saved runs |
| `GET /api/runs/{id}` | Read saved state, status and checkpoint ID |
| `POST /api/runs/{id}/review` | Submit `action` (`approve` or `revise`), `feedback` and the current `checkpoint` |
| `POST /api/runs/{id}/continue` | Explicitly continue an interrupted or failed step |

```sh
curl "$APP_URL/api/runs" \
  -H "Authorization: Bearer $APP_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"request":"Write a friendly workshop announcement."}'
```

Use the returned run ID and checkpoint ID when reviewing. Revision feedback is required. A stale checkpoint or a run already being processed returns HTTP 409; fetch the current state before deciding what to do next. Treat a returned `error` field as a failed step even when the request returns HTTP 200: the response includes the saved run ID so it can be continued.

Browser sessions use signed HttpOnly cookies, Secure cookies on Runtime, an eight-hour expiry, and CSRF tokens for writes. Login allows 10 attempts per minute across this small shared app instance. Signing out removes the browser cookie. Changing `SESSION_SECRET` invalidates existing cookies. Per-user accounts, immediate session revocation and distributed rate limiting are outside this starter's scope.

## Persistence and execution limits

`workflow.py` defines the graph. LangGraph's PostgreSQL checkpointer saves graph state; `starter_runs` holds the request index. The review node uses `interrupt()` and resumes through `Command(resume=...)`. A PostgreSQL advisory lock serializes mutations for each run, and checkpoint IDs reject stale review submissions.

At most four workflow executions run concurrently per process, leaving room in the connection pool for checkpoint writes. A busy workspace returns HTTP 503. Refresh saved runs before retrying: a newly created run may already have been saved and can be continued.

**There is no durable background-job scheduler.** HTTP requests drive execution until it finishes, fails or pauses. Saved state survives restarts, but unfinished work resumes only when you select **Continue saved run** or call the corresponding API. A lost browser response does not necessarily mean execution failed: refresh the saved runs before creating another request. Creating a run is not idempotent.

A crash between an external model call and its checkpoint can cause that call to be repeated on resume. This example only drafts text. If you add payments, messages or other external side effects, implement idempotency for those operations. Keep side effects outside the code preceding an `interrupt`, because that node restarts when resumed.

Requests, drafts and feedback are stored in PostgreSQL. Use synthetic data initially, configure retention and backups for longer use, and back up before dependency/schema upgrades. No automatic retention or deletion policy is included. Keep one replica and one worker for this demo; multi-replica operations, queueing, load testing and HA are not implemented as a platform here.

## Development and validation

Use Python 3.12:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt -c constraints.txt
.venv/bin/python -m pytest -q
```

Direct dependencies and the resolved dependency set are pinned. `constraints.txt` records the tested resolution; refresh it deliberately when upgrading. Modify `workflow.py` to replace the draft and review nodes, then update the UI and API if the new state needs different inputs.

Tests use an in-memory checkpointer and run index; production has no in-memory fallback. See [VALIDATION.md](VALIDATION.md) for completed checks and pending live PostgreSQL tests. Runtime may ignore Dockerfile HEALTHCHECK, so verify readiness and workflow behaviour separately.

## References

- [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)
- [PostgreSQL checkpointing](https://docs.langchain.com/oss/python/langgraph/add-memory)
- [Pause and resume with interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [Aiven Runtime Compose manifests](https://aiven.io/docs/products/runtime/manifest-files/compose-files)

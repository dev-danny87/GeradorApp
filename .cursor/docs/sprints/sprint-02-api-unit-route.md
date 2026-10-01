# Sprint 02 — API auth and unit route

## Goal

A person can start GeradorApi locally, send one real diff file to `POST /v1/analyze/unit`, and get tasks back. A wrong bearer token returns `401`. The process exits at startup when `CLAUDE_KEY` is missing.

## Depends on

Sprint 01

## In scope

- Copy `services/ai_api_request.py` into `GeradorApi/core/ai_pipeline.py` and copy `attach_commit_links_to_tasks` plus `strip_urls_from_description` into `core/commit_links.py`. Leave the rest of `utils/commit_metadata.py` in this repo.
- Point Claude auth at the server environment `CLAUDE_KEY`. Optional `ANTHROPIC_BASE_URL` defaults to `https://api.anthropic.com/v1`. Do not read `~/taskManager/ge.txt`.
- `app/main.py` (CORS off), `app/auth.py` (constant-time bearer compare to `API_TOKEN`), and `POST /v1/analyze/unit` plus `GET /v1/models` in `app/routes/analyze.py`.
- The unit route runs the per-file body: prompt, Claude call, validation, commit-link attach, and URL strip. It returns `{"tasks": [...]}`.
- Enforce `MAX_DIFF_CHARS`, `MAX_UNIT_CHARS`, and `MIN_DIFF_CHARS` on the server. A diff that is empty or under `MIN_DIFF_CHARS` after the same filters the client uses today returns `422` and does not call Claude. The server may also split an oversized unit as a safety check; the client remains the primary splitter.
- Missing `CLAUDE_KEY` fails process startup, before any request.
- Log model id, byte size, duration, and HTTP status. Do not log diff text or task descriptions.
- Document the run command: `uvicorn app.main:app --host 0.0.0.0 --port 8000`, one worker, internal network only, bearer token required. TLS is required when the hop crosses an untrusted network. No database and no job table.

## Out of scope

- `POST /v1/analyze/merge`, `/estimate`, `/pack`, and `/synthesize`.
- Any Flet change, `services/api_client.py`, and deleting `services/ai_api_request.py` from this repo.
- Per-user API accounts. One shared `API_TOKEN` is enough.

## Touches

- `GeradorApi`: `app/main.py`, `app/auth.py`, `app/routes/analyze.py`, `core/ai_pipeline.py`, `core/commit_links.py`, `README.md`.
- This repo is not modified. `services/ai_api_request.py` and `utils/commit_metadata.py` are the copy source.

## Done when

- Starting uvicorn without `CLAUDE_KEY` exits before it serves traffic.
- `GET /v1/models` with `Authorization: Bearer <API_TOKEN>` returns the five `MODEL_CONFIGS` ids and their `max_tokens`.
- `POST /v1/analyze/unit` with a normal fixture diff returns at least one task, and `description` has no raw URLs. `commit_links` are present when the diff contains commit URLs.
- The same route with a fixture under `MIN_DIFF_CHARS` returns `422` and `{"detail": "..."}`.
- A missing bearer and a wrong bearer both return `401`.
- The access log for the successful unit call shows model id, byte size, duration, and status, and does not contain the diff body.

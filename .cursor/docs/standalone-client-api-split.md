# Standalone Flet client and hosted analysis API

This plan splits GeradorApp into two Python projects:

- **This repo** stays the Windows desktop app: Flet UI, Redmine login, Git fetch, local files, and Redmine writes.
- **A new repo** hosts the analysis API: Claude calls, prompts, merge, hour estimates, and packing.

The desktop app keeps talking to Redmine and Git from the user's machine. The hosted API never receives a Redmine session, a Redmine password, or a Git token.

## Decision: stay on Python and Flet

Do not rewrite the desktop app in another language.

The client is still a local integration worker after the split. It logs into Redmine with a cookie session, scrapes HTML, calls GitLab or GitHub, writes `./diffs`, Excel, and PDFs, and creates issues with that same session. That code already runs in Python, and the installer path (`flet pack` plus Inno Setup) already exists.

Flet matches the current UI: tabs, forms, date fields, progress, and a log console. After the split, the analysis tab calls the hosted API instead of `analyze_diffs_grouped_with_claude`. The other tabs keep doing local I/O.

A C#, Tauri, Electron, or Flutter rewrite would port the scrapers and the UI to make the HTTP calls slightly nicer. Do that later only if packaging size, startup time, or Flet upgrades become a real problem. The API split does not require it.

Keep the new backend in Python (FastAPI). `services/ai_api_request.py` moves almost as-is, and both sides share the same task JSON.

## Why the boundary is drawn here

Redmine access is an HTML session, not an API key that can be forwarded.

- `services/auth_service.py` logs into SSP (`https://redmine.ssp.go.gov.br`), PGE (`https://projetos.procuradoria.go.gov.br/contrato17`), or IPHAN (`https://redmine.iphan.gov.br/redmine`) and returns a `requests.Session`.
- IPHAN already disables SSL verification on some machines because the certificate chain is missing from the local CA store.
- `diff_task_automation.create_ai_redmine_tasks` and `task_automation.py` scrape a CSRF token and post issues with that session.
- Evidence flows (`main.generate_evidences`, `services/pge_evidence_service.py`, `services/iphan/*`) download attachments onto the user's disk.
- GitLab and GitHub tokens live in `~/taskManager/ge.txt` and are read only by `services/gitlab_service.py` and `services/github_service.py`.

Those hosts are reachable from the user's network. A hosted server should not hold those credentials, and it may not be able to reach the hosts at all.

The analysis pipeline is the opposite. `analyze_diffs_grouped_with_claude` already takes plain text in and returns task JSON out. The Anthropic key is the secret that should leave the desktop.

```
Flet client (this repo)                         GeradorApi (new repo)
─────────────────────                           ─────────────────────
UI, login, tabs                                 FastAPI
Redmine session + issue create                  Claude calls, prompts
GitLab / GitHub fetch → ./diffs                 merge, hour estimate, pack
Save JSON, Excel, PDFs locally                  CLAUDE_KEY only here
HTTP client to the API
```

The client fetches. The API computes. The client writes.

## What stays in this repo

| Area | Files | Reason |
|---|---|---|
| UI shell | `main.py`, `layout/*`, `utils/ui_components.py`, `utils/month_selector.py` | Flet screens and local state |
| Redmine login | `services/auth_service.py` | Cookie session only works from the user's network |
| Git fetch | `services/gitlab_service.py`, `services/github_service.py`, `layout/tab_diffs.py` | Tokens and internal Git hosts |
| Issue create / close | `diff_task_automation.py`, `task_automation.py`, `layout/tab_tasks.py`, `layout/tab_close_tasks.py`, `layout/tab_banco_horas.py` | Live session and CSRF |
| Evidences | `main.generate_evidences`, `services/pge_evidence_service.py`, `services/iphan/*`, `layout/tab_evidences*.py` | Scrape plus download to the user's folders |
| Local config and files | `utils/app_config.py`, `utils/ai_tasks_store.py`, `utils/banco_horas_store.py`, `utils/output_paths.py` | `~/taskManager/ge.txt`, `./diffs`, `./ai_tasks` |
| Fechamento assembly | `utils/fechamento_builder.py` | Reads local diff folders and saved JSON, then the client posts to Redmine |
| Commit URL parsing | `utils/commit_metadata.py` | Pure parse of text the client already has; see the unit-step note below |
| PDF join and updates | `layout/view_join_documents.py`, `utils/pdf_merger.py`, `services/update_service.py`, `scripts/build_installer.ps1` | Local files and the `.exe` |
| Catalogs used by forms | `redmine_mappings.py`, `utils/redmine_task_defaults.py`, `utils/redmine_version.py` | Dropdowns and Redmine field ids stay next to the writer that posts them |

Evidence generation stays on the client for this cut. Those flows are I/O. Moving them would mean shipping HTML and attachments to the server.

## What moves to the API repo

Move the body of `services/ai_api_request.py`:

- `MODEL_CONFIGS`, prompts, and JSON schemas
- `_call_claude_sync` and the Anthropic HTTP client
- Per-file task creation (`_build_task_create_prompt`, unit split, truncation limits)
- `_merge_tasks_chunked` and merge-group validation
- `_estimate_hours_chunked`
- `_pack_tasks_to_min_hours` and `_finalize_free_hours`
- `analyze_diffs_grouped_with_claude` (the orchestration the server exposes as steps)
- `synthesize_tasks_for_redmine` (also called from `layout/tab_close_tasks.py`)

`CLAUDE_KEY` leaves `ge.txt`, `.env.example`, and the Config tab. The desktop config gains `API_BASE_URL` and `API_TOKEN`.

Two callers stop importing Claude and call `services/api_client.py` instead:

- `layout/tab_ai_analysis.py` — `analyze_diffs_grouped_with_claude`
- `layout/tab_close_tasks.py` — `synthesize_tasks_for_redmine` and `MODEL_CONFIGS`

`layout/tab_banco_horas.py` does not call Claude today. It creates Redmine issues from already-built tasks through `create_ai_redmine_tasks`. Leave that call local.

### Commit links during a unit

Inside the unit loop, the current code calls `attach_commit_links_to_tasks` and `strip_urls_from_description` from `utils/commit_metadata.py` before the checkpoint is saved. The server receives the diff text, so it can run those two functions and return tasks that already have `commit_links` and descriptions without raw URLs.

Copy those two functions into the API repo with the pipeline. Leave the rest of `utils/commit_metadata.py` on the client. Fechamento still reads local diff files and builds Redmine notes there.

## What crosses the network

Sent to the API:

- Diff text for one file (or one oversized chunk) per unit call
- Compact task JSON for merge, estimate, pack, and synthesize
- Model id, catalog role (`atribuicao_catalogo`), and `min_hours`

Never sent to the API:

- Redmine username, password, or session cookies
- `GITLAB_TOKEN`, `GITHUB_TOKEN`
- `CLAUDE_KEY` (it lives only on the server)
- Local filesystem paths, except as opaque labels the client uses to resume (`diff_YYYY-MM-DD.txt`)

Diff text is source code. That is required for the model to read it. Host the API where desktops can reach it, require a bearer token, and do not put the service on the public internet.

## API shape

Do not wrap `analyze_diffs_grouped_with_claude` in one long HTTP call. A full run is many Claude requests, with `ai_tasks_checkpoint.json` in the diff folder and a cancel button. One request will time out, and a server-side job dies if the process restarts.

Keep the loop on the client. One HTTP call equals one pipeline step. The server stays stateless: it does not store the checkpoint.

The current function in `services/ai_api_request.py` is the spec:

1. Each diff file becomes tasks (checkpoint after every file).
2. Merge deduplicates those tasks.
3. Estimate adjusts hours for the catalog role without forcing a global total.
4. Pack merges small tasks until each has at least `min_hours`.

Limits already in the client must be enforced again on the server: `MAX_DIFF_CHARS` 150_000, `MAX_UNIT_CHARS` 120_000, `MIN_DIFF_CHARS` 150, `AI_BATCH_SIZE` 40.

### Auth

Every route except a future health check requires:

```
Authorization: Bearer <API_TOKEN>
```

The desktop stores that token in `ge.txt`. It is unrelated to the Redmine login. Compare it to the server env var with a constant-time check. Reject missing or wrong tokens with `401`.

### `GET /v1/models`

Replaces the hardcoded `MODEL_CONFIGS` dropdown.

```json
{
  "models": [
    {"id": "claude-sonnet-5", "max_tokens": 65536},
    {"id": "claude-opus-4-8", "max_tokens": 16384}
  ]
}
```

The list is whatever `MODEL_CONFIGS` contains at implementation time. The client falls back to the last known list if this call fails, so the tab still opens offline.

### `POST /v1/analyze/unit`

One diff file in, tasks for that file out. This is the body of the per-file loop, including prompt, Claude call, validation, commit-link attach, and URL strip.

Request:

```json
{
  "model": "claude-sonnet-5",
  "atribuicao_catalogo": "Desenvolvedor Sênior",
  "label": "diff_2026-03-01.txt",
  "filename": "diff_2026-03-01.txt",
  "content": "<diff text>"
}
```

Response `200`:

```json
{
  "tasks": [
    {
      "task_title": "...",
      "category": "Feature",
      "estimated_hours": 3.0,
      "description": "...",
      "affected_files": ["src/Foo.java"],
      "commit_links": ["https://..."]
    }
  ]
}
```

Response `422` when the diff is empty or below `MIN_DIFF_CHARS` after the same filters the client uses today. The client records that label in `failed_labels` and continues, matching the current `except` path that does not abort the whole run.

The client still splits oversized files with the same rules as `_build_diff_units` before calling this route, so the server receives one unit at a time. Duplicating the splitter on the server is a safety check, not the primary path.

### `POST /v1/analyze/merge`

Request:

```json
{
  "model": "claude-sonnet-5",
  "tasks": [],
  "min_hours": 8
}
```

`min_hours` is unused by the current merge prompt. Accept it so the client can send one context object. Response is the merged task list, same task object shape. The server runs `_merge_tasks_chunked` with `_build_merge_tasks_prompt`. If the caller passes `"cancel_hint": true` the server finishes the current batch and returns what it has; the client owns real cancellation by simply not calling the next route.

### `POST /v1/analyze/estimate`

Request: `model`, `atribuicao_catalogo`, `tasks`. Response matches `_finalize_free_hours` plus the tasks with adjusted hours:

```json
{
  "mathematical_reconciliation": {
    "target_total_hours": 40.0,
    "allocation_rationale_pt": "..."
  },
  "tasks": []
}
```

### `POST /v1/analyze/pack`

No Claude call. Request: `tasks`, `min_hours`, and the rationale string from the estimate step. Response is the same wrapper as today's final payload from `_pack_and_stamp`:

```json
{
  "mathematical_reconciliation": {
    "target_total_hours": 40.0,
    "allocation_rationale_pt": "..."
  },
  "tasks": [],
  "atribuicao_catalogo": "Desenvolvedor Sênior",
  "min_hours": 8
}
```

Task ids (`task-0001`, ...) are assigned here, as `_assign_task_ids` does today.

### `POST /v1/analyze/synthesize`

Used by the close-tasks tab. Same behavior as `synthesize_tasks_for_redmine`: AI grouping, then local packing so each task has at least `min_hours` while preserving the original total.

Request: `model`, `tasks`, `min_hours`. Response: `{ "tasks": [] }`.

### Errors

Use a single error body:

```json
{"detail": "Resposta truncada pelo limite de tokens (stop_reason=max_tokens)."}
```

Map Claude failures and validation errors to `502` when the upstream call failed, and `422` when the input is invalid. The client shows `detail` in the same status line that today shows `Erro no processamento com IA: ...`.

Timeouts: unit, merge, and estimate calls can run for several minutes. The client timeout should be at least 10 minutes per call. Pack and models stay under 30 seconds.

## Client orchestration

Add `services/api_client.py`. It reproduces the control flow of `analyze_diffs_grouped_with_claude` without calling Claude itself.

Behavior to preserve, because `layout/tab_ai_analysis.py` already depends on it:

- Signature seen by the tab stays the same: `diff_items`, `selected_model`, `on_progress(step, total, message)`, `output_dir`, `should_cancel`, `atribuicao_catalogo`, `min_hours`.
- Progress math stays `total_steps = len(units) + 3` (units, merge, estimate, pack).
- Checkpoint file stays `ai_tasks_checkpoint.json` inside the diff folder (`CHECKPOINT_FILENAME`). The client writes it after every unit, including failed labels. Shape:

```json
{
  "completed_units": 2,
  "total_units": 5,
  "processed_labels": ["diff_2026-03-01.txt", "diff_2026-03-02.txt"],
  "failed_labels": [],
  "unit_tasks": [{"tasks": []}, {"tasks": []}]
}
```

- Labels and `unit_tasks` must stay the same length. A mismatch means "ignore the checkpoint and reprocess", which is what `_load_units_checkpoint` does today.
- `should_cancel` is checked between HTTP calls. On cancel after at least one successful unit, the client calls pack locally via `POST /v1/analyze/pack` on the tasks gathered so far and sets `partial: true`, `cancelled_after_units`, and `total_units`. It does not call merge or estimate. That matches the current branch that finishes a cancelled run without more network calls to Claude. Pack is a local rule on the server, so one short call is acceptable; if the API is down, pack with a copied `_pack_tasks_to_min_hours` is unnecessary. Fail the cancel-finish with the same error surface instead of silently diverging.
- After the final payload returns, the tab still adds `source_diff_folder`, `generated_at`, `generated_by`, and `model`, then `save_results` writes `./ai_tasks`. Do not move that save to the server.

`synthesize_tasks_for_redmine` becomes a one-line wrapper over `POST /v1/analyze/synthesize` so `layout/tab_close_tasks.py` keeps its `synthesize_fn` argument.

Model dropdowns call `GET /v1/models` when the tab is built, and keep today's `MODEL_CONFIGS` keys as the offline fallback until the first successful fetch. After the API is required for a run, remove the duplicated dict from the client so the server is the only list.

## Config

`utils/app_config.py` keys today include `CLAUDE_KEY`. Change the desktop template as follows.

Remove from `GE_TXT_DEFAULTS`, the Config tab (`layout/tab_config.py` `_FIELD_LABELS` and the password field list), and `.env.example`:

- `CLAUDE_KEY`

Add:

- `API_BASE_URL` — example `http://10.0.0.5:8000`
- `API_TOKEN` — bearer token, password field in the Config tab

Leave Git and Redmine keys where they are: `GITLAB_TOKEN`, `GITHUB_TOKEN`, `RD_PASS`, author defaults, `RD_MIN_TASK_HOURS`, and the SSP dropdown defaults.

On the server, environment only:

- `CLAUDE_KEY`
- `API_TOKEN` (the value the desktop sends)
- `ANTHROPIC_BASE_URL` optional, default `https://api.anthropic.com/v1`

Existing `ge.txt` files will still contain `CLAUDE_KEY`. Ignore that key on the client. Do not delete it automatically; users may roll back a version. Document that the key on the desktop is unused once this ships.

## Repository layout

Create the API as a sibling folder and its own git repo, not a package inside this repo. Separate deploy, separate secrets, separate requirements. The server image does not include Flet or PyInstaller.

```
GeradorApi/
  app/main.py                 # FastAPI app, CORS off, bearer dependency
  app/routes/analyze.py       # the five POST routes + GET /v1/models
  app/auth.py                 # bearer check
  core/ai_pipeline.py         # moved from services/ai_api_request.py
  core/commit_links.py        # attach_commit_links_to_tasks + strip_urls_from_description
  core/schemas.py             # pydantic models for the JSON above
  .env.example                # CLAUDE_KEY, API_TOKEN
  requirements.txt            # fastapi, uvicorn, requests, pydantic
  README.md                   # run, env, and the contract
```

This repo, after the cut:

```
services/api_client.py        # loop, checkpoint, timeouts, error text
layout/tab_ai_analysis.py     # imports api_client instead of ai_api_request
layout/tab_close_tasks.py     # synthesize_fn points at the client wrapper
layout/tab_config.py          # API_BASE_URL, API_TOKEN; no CLAUDE_KEY
```

Delete `services/ai_api_request.py` from the client only after `api_client` returns the same dict the two tabs already expect and a manual run against a local API succeeds.

Copy the pipeline once. Do not add a third shared package until the JSON shape stops changing. The task object in `TASK_SCHEMA` inside `ai_api_request.py` is the contract.

## Order of work

### 1. Freeze the contract

Write the request and response models from the JSON in this document before moving code. Confirm against:

- `analyze_diffs_grouped_with_claude` arguments and the dict it returns (`tasks`, `mathematical_reconciliation`, `atribuicao_catalogo`, `min_hours`, `partial`, `failed_units`)
- `synthesize_tasks_for_redmine` return value (a list of tasks)
- Checkpoint keys in `_save_units_checkpoint`

### 2. Stand up GeradorApi with the moved file

Copy `services/ai_api_request.py` into `core/ai_pipeline.py`. Point `_get_headers` at the server env `CLAUDE_KEY` instead of `get_config`. Expose the routes. Run one real diff file through `POST /v1/analyze/unit` before touching Flet.

Acceptance: a unit call with a small diff returns `tasks`. A wrong bearer token returns `401`. A missing `CLAUDE_KEY` on the server fails at startup, not on the first user click.

### 3. Client adapter behind the existing UI

Add `services/api_client.py` with the progress and cancel behavior above. Swap the import in `layout/tab_ai_analysis.py` only. Keep `create_ai_redmine_tasks` local.

Acceptance: analyze a diff folder, stop mid-run, run again, and confirm the checkpoint skips completed labels. The status line still shows `[step/total] message`. A down API shows the error in that same status line.

### 4. Close-tasks synthesize

Point `layout/tab_close_tasks.py` at `POST /v1/analyze/synthesize`. Redmine closing stays in `task_automation.py`.

### 5. Config

Remove `CLAUDE_KEY` from the Config tab, `GE_TXT_DEFAULTS`, and `.env.example`. Add `API_BASE_URL` and `API_TOKEN`. Update the README config section.

### 6. Package the desktop app

`flet pack` and `scripts/build_installer.ps1` stay as documented in the README. Bump `CURRENT_VERSION` in `main.py` and the Inno Setup version together when this ships, because desktops without `API_BASE_URL` cannot analyze.

The client still needs `requests`, BeautifulSoup, pandas, and openpyxl for Redmine, Git, and evidences. Dropping those is out of scope.

## Hosting

- Bind the API on an internal address the desktops can reach.
- Terminate TLS if the hop crosses a network you do not trust. Diff text is source code.
- One shared `API_TOKEN` is enough for this internal tool. Per-user accounts are a later change and must still be separate from Redmine login.
- Log model id, byte size, duration, and HTTP status. Do not log the diff body or the task descriptions.
- Enforce the character limits on every unit request so a huge paste cannot run up the Claude bill.
- Run a single worker process first. The pipeline is I/O bound on Anthropic. Add workers only after you see queueing.

Suggested process:

```
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

No database. No job table. The checkpoint on the client is the resume mechanism.

## Testing

API, before the Flet switch:

- Unit route with a fixture diff under `MIN_DIFF_CHARS` returns `422`.
- Unit route with a normal fixture returns at least one task and strips raw URLs from `description`.
- Merge route keeps every input index represented (the current `_validate_merge_groups` rule).
- Pack route with `min_hours` 8 never returns a task under 8 hours unless there is only one task whose total is already under 8 (current `_pack_tasks_to_min_hours` behavior: a single task is returned as-is).
- Estimate route rejects a model id that is not in `MODEL_CONFIGS`.
- Bearer missing and bearer wrong both return `401`.

Client, against a local API:

- Full analysis of a folder with two diff files writes `ai_tasks_checkpoint.json` and a result under the ai-tasks directory.
- Cancel after the first file produces a payload with `partial: true` and does not call merge or estimate (watch the API access log).
- Second run on the same folder does not call `/unit` for labels already in the checkpoint.
- Create Redmine tasks from the result still uses the local session (`create_ai_redmine_tasks`). No Redmine host appears in the API access log.
- Diff tab still calls GitLab or GitHub directly. Those tokens do not appear in API requests.
- Config save writes `API_BASE_URL` and `API_TOKEN` and does not send them anywhere except the `Authorization` header and the base URL.

## Out of scope

- Rewriting the UI in another language.
- Moving evidence scrapers, PDF join, or Redmine issue creation to the server.
- Sending the Redmine session to the server or proxying Redmine through it.
- A server-side job queue, websockets, or stored checkpoints.
- A shared installable Python package for the task schema.
- Per-user API accounts.
- Deleting leftover `CLAUDE_KEY` lines from existing `ge.txt` files.

## Risks

- **Source code leaves the machine.** Diff text is posted to the internal API and then to Anthropic. That is the point of the split. Keep the API internal.
- **Contract drift.** The client loop and the server steps can disagree on checkpoint shape. Treat the JSON in this document as the contract and change both sides in the same release.
- **Cancel semantics.** Today, cancel skips merge and estimate and packs locally. The client must keep that, or a cancel will spend more Claude tokens than the current app.
- **Timeouts.** A single unit can approach the model limit (`max_tokens` up to 128000 on some entries in `MODEL_CONFIGS`). Size the HTTP timeout for that, and surface `stop_reason=max_tokens` as the same Portuguese message the app shows now.
- **Offline analysis.** After this ships, analysis requires the API. Git fetch, Redmine login, evidences, and opening saved JSON still work offline.

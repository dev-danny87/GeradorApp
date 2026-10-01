# Sprint 06 — Desktop config

## Goal

A person can open the Config tab, save an API base URL and a bearer token, and reopen the app with those values loaded. The Claude key field is gone. Analysis uses only the new pair.

## Depends on

Sprint 05

## In scope

- Remove `CLAUDE_KEY` from `GE_TXT_DEFAULTS` in `utils/app_config.py`, from `layout/tab_config.py` (`_FIELD_LABELS` and the password field list), and from `.env.example`.
- Add `API_BASE_URL` (example `http://10.0.0.5:8000`) and `API_TOKEN` (password field on the Config tab).
- Leave `GITLAB_TOKEN`, `GITHUB_TOKEN`, `RD_PASS`, author defaults, `RD_MIN_TASK_HOURS`, and the SSP dropdown defaults where they are.
- Existing `ge.txt` files may still contain `CLAUDE_KEY`. The client ignores that key. Do not delete it automatically.
- Update the README config section: the desktop key is unused once this ships, and analysis needs `API_BASE_URL` and `API_TOKEN`.
- `services/api_client.py` sends `API_TOKEN` only as `Authorization: Bearer ...` and uses `API_BASE_URL` only as the request base. It never sends those values in a JSON body, and it never sends Redmine or Git secrets.

## Out of scope

- Deleting leftover `CLAUDE_KEY` lines from existing `ge.txt` files.
- Server env changes beyond what sprint 02 already documents (`CLAUDE_KEY`, `API_TOKEN`, optional `ANTHROPIC_BASE_URL` on the API only).
- The installer build and the version bump (sprint 07).
- Per-user API accounts.

## Touches

- This repo: `utils/app_config.py`, `layout/tab_config.py`, `.env.example`, `README.md`, and `services/api_client.py` if the key names are not already the ones it reads.

## Done when

- The Config tab shows `API_BASE_URL` and a masked `API_TOKEN`, and it does not show a Claude API key field.
- Saving config writes `API_BASE_URL` and `API_TOKEN` into `~/taskManager/ge.txt` and does not write a new `CLAUDE_KEY`.
- A `ge.txt` that still has an old `CLAUDE_KEY` line still loads, and analysis does not read that line.
- Git and Redmine fields still save and still stay off the API requests.
- The README config section lists `API_BASE_URL` and `API_TOKEN` and says the desktop Claude key is unused.

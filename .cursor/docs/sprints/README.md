# Sprints

Source: `.cursor/docs/standalone-client-api-split.md`

## Sequence

| Sprint | Title | Depends on | Outcome |
| --- | --- | --- | --- |
| 01 | Freeze the HTTP contract | none | GeradorApi has pydantic models for every request and response in the plan, checked against the current task JSON, synthesize list, and checkpoint keys. |
| 02 | API auth and unit route | 01 | A local GeradorApi accepts one diff file, rejects a bad bearer token, and refuses to start without `CLAUDE_KEY`. |
| 03 | Merge, estimate, pack, and synthesize | 02 | The remaining analyze routes run as separate stateless calls, including the API checks that must pass before the Flet switch. |
| 04 | Client analysis adapter | 03 | The analysis tab runs the same loop through `services/api_client.py`, with checkpoint resume and cancel between calls. |
| 05 | Close-tasks synthesize | 04 | The close-tasks tab groups tasks through `POST /v1/analyze/synthesize`, and the desktop copy of the Claude module is removed. |
| 06 | Desktop config | 05 | Config stores `API_BASE_URL` and `API_TOKEN`. `CLAUDE_KEY` is no longer a desktop setting. |
| 07 | Package the desktop app | 06 | The Flet installer ships the client that cannot analyze without the API, with the app version and Inno Setup version bumped together. |

## Mismatches

- `GET /v1/models` in the plan shows two sample models. `MODEL_CONFIGS` in `services/ai_api_request.py` has five: `claude-sonnet-5` (65536), `claude-opus-4-8` (16384), `claude-haiku-4-5-20251001` (32768), `claude-opus-5-5` (128000), `claude-sonnet-5-5` (128000). The plan already says to ship whatever that dict contains. These sprints use the five live entries.
- The estimate and pack samples set `target_total_hours` to `40.0`. `_finalize_free_hours` sets that field to the sum of `estimated_hours`. These sprints follow that function. The sample number is only the field’s shape.
- `CHECKPOINT_FILENAME` (`ai_tasks_checkpoint.json`) is defined in both `services/ai_api_request.py` and `utils/fechamento_builder.py`. The string matches. Fechamento stays on the client and keeps reading that filename.

None of these make a sprint impossible. Cited files still exist and the boundary matches the plan: Redmine login, Git fetch, evidence download, and issue writes stay in this repo; Claude, merge, estimates, packing, and `synthesize_tasks_for_redmine` are what move.

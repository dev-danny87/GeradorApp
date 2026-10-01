# Sprint 07 — Package the desktop app

## Goal

A person can build the Windows installer from the documented script and install a Flet desktop app whose version matches Inno Setup. Analysis in that build calls the hosted API. Git fetch, Redmine login, evidences, and opening saved JSON still work without the API.

## Depends on

Sprint 06

## In scope

- Keep this repo a Flet desktop app. Package it with `flet pack` and `scripts/build_installer.ps1` as the README already describes.
- Bump `CURRENT_VERSION` in `main.py` and `#define MyAppVersion` in `installer/Gerador_Redmine.iss` to the same new value. Desktops that only have `CLAUDE_KEY` cannot analyze after this ships, so the installer version must move with the app version.
- The client requirements still include `requests`, BeautifulSoup, pandas, and openpyxl for Redmine, Git, and evidences.
- The API repo stays a separate deploy. Its image does not include Flet or PyInstaller.

## Out of scope

- Rewriting the UI in another language.
- Dropping Redmine, Git, or evidence dependencies from the client.
- Moving evidence scrapers, PDF join, or Redmine issue creation into the API.
- A shared Python package, a job queue, or per-user API accounts.
- Deleting leftover `CLAUDE_KEY` lines from existing `ge.txt` files.

## Touches

- This repo: `main.py` (`CURRENT_VERSION`), `installer/Gerador_Redmine.iss`, `scripts/build_installer.ps1` only if the documented pack command needs a path fix, and the README install section if the version note needs the new pair of values.
- `GeradorApi` is not packed into the desktop installer.

## Done when

- `CURRENT_VERSION` and `MyAppVersion` are the same value and are greater than `1.0.0`.
- `scripts/build_installer.ps1` produces an installer, and the installed app opens the existing tabs.
- In that build, analysis without a reachable `API_BASE_URL` fails on the analysis status line, and the diff, login, and evidence tabs still run locally.
- The installer does not contain `CLAUDE_KEY` as a required setting and does not embed the API’s Anthropic key.

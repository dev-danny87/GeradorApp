import datetime
import os

from services.iphan._common import (
    BACKLOG_PDF_NAME,
    download_file,
    build_output_dirs,
    is_app_running,
    options_cache,
    safe_filename,
    set_app_run,
    timestamp,
)
from services.iphan._date_controls import build_date_controls
from services.iphan._error_registry import (
    begin_error_registry,
    error_registry_summary,
    write_error_registry,
)
from services.iphan._project_files import (
    fetch_project_files_html,
    filter_files_for_sprints,
    parse_project_files_html,
)
from services.iphan._wiki_backlog import (
    BACKLOG_PDF_URL,
    BACKLOG_WIKI_URL,
    collect_matching_rows,
    fetch_backlog_html,
    filter_sprints_by_end_date,
    parse_backlog_html,
)
from utils.output_paths import month_label_from_date
from services.iphan._wiki_download import download_wiki_rows

PROJECT_KEY = "editais_iphan"
PROJECT_LABEL = "EDITAIS IPHAN"


def _ensure_date_controls(cache: dict):
    return build_date_controls(cache)


def load_options(session, app_state):
    cache = options_cache(app_state, PROJECT_KEY)
    _ensure_date_controls(cache)
    cache["loaded"] = True


def get_controls(app_state):
    cache = options_cache(app_state, PROJECT_KEY)
    _ensure_date_controls(cache)
    return cache.get("controls", [])


def validate_selection(app_state):
    cache = options_cache(app_state, PROJECT_KEY)
    date_start, date_end = _ensure_date_controls(cache)

    start_raw = (date_start.value or "").strip()
    end_raw = (date_end.value or "").strip()
    if not start_raw or not end_raw:
        return False, "Informe a data inicial e a data final."

    try:
        start_date = datetime.datetime.strptime(start_raw, "%Y-%m-%d").date()
        end_date = datetime.datetime.strptime(end_raw, "%Y-%m-%d").date()
    except ValueError:
        return False, "Datas inválidas. Use o formato AAAA-MM-DD."

    if start_date > end_date:
        return False, "A data inicial não pode ser posterior à data final."

    cache["start_date"] = start_date
    cache["end_date"] = end_date
    return True, ""


def _download_pf_reports(session, sprint_numbers: set[int], dirs: dict) -> tuple[int, int]:
    if not sprint_numbers:
        return 0, 0

    print(f"\n[{timestamp()}] Buscando arquivos do projeto (PF por sprint)...")
    files_html = fetch_project_files_html(session)
    entries = filter_files_for_sprints(parse_project_files_html(files_html), sprint_numbers)

    if not entries:
        print(f"[{timestamp()}] Nenhum arquivo PF encontrado para sprints: {sorted(sprint_numbers)}")
        return 0, 0

    ok_count = 0
    fail_count = 0
    for entry in entries:
        if not is_app_running():
            break
        dest_path = os.path.join(dirs["pf_contagem"], safe_filename(entry.filename))
        print(
            f"[{timestamp()}] PF Sprint #{entry.sprint_number}: {entry.filename}"
            + (f" ({entry.created_on})" if entry.created_on else "")
        )
        if download_file(
            session,
            entry.download_url,
            dest_path,
            context=f"PF Sprint #{entry.sprint_number} | {entry.filename}",
        ):
            ok_count += 1
        else:
            fail_count += 1

    return ok_count, fail_count


def generate_evidences(session, app_state, *, start_run=True):
    if start_run:
        set_app_run(True)

    if not session:
        print(f"[{timestamp()}] ERROR: Sessão inválida. Faça login primeiro.")
        return

    ok, message = validate_selection(app_state)
    if not ok:
        print(f"[{timestamp()}] ERROR: {message}")
        return

    begin_error_registry(PROJECT_KEY)

    cache = options_cache(app_state, PROJECT_KEY)
    start_date = cache["start_date"]
    end_date = cache["end_date"]

    dirs = build_output_dirs(PROJECT_KEY, month_label_from_date(start_date))
    print(f"\n[{timestamp()}] Preparando evidências {PROJECT_LABEL}...")
    print(f"Período: {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}")
    print(f"Pasta de saída: {dirs['base']}")

    print(f"\n[{timestamp()}] Lendo backlog wiki...")
    backlog_html = fetch_backlog_html(session, BACKLOG_WIKI_URL)
    all_sprints = parse_backlog_html(backlog_html)
    matched_sprints = filter_sprints_by_end_date(all_sprints, start_date, end_date)
    sprint_numbers = {sprint.sprint_number for sprint in matched_sprints}
    rows = collect_matching_rows(matched_sprints)

    print(f"[{timestamp()}] Sprints no período: {len(matched_sprints)} ({sorted(sprint_numbers)})")
    print(f"[{timestamp()}] Itens Concluído com wiki: {len(rows)}")

    wiki_ok, wiki_fail = download_wiki_rows(session, rows, dirs, developer_only=True)
    pf_ok, pf_fail = _download_pf_reports(session, sprint_numbers, dirs)

    backlog_dest = os.path.join(dirs["base"], BACKLOG_PDF_NAME)
    print(f"\n[{timestamp()}] Baixando {BACKLOG_PDF_NAME}...")
    backlog_ok = download_file(session, BACKLOG_PDF_URL, backlog_dest, context=BACKLOG_PDF_NAME)

    write_error_registry(dirs["base"])

    print(f"\n[{timestamp()}] Resumo:")
    print(f"  Wiki PDFs: {wiki_ok} ok, {wiki_fail} falha(s)")
    print(f"  PF por sprint: {pf_ok} ok, {pf_fail} falha(s)")
    print(f"  Backlog.pdf: {'ok' if backlog_ok else 'falha'}")
    print(f"  {error_registry_summary()}")
    print(f"\n[{timestamp()}] Fim! DIRETORIO_FINAL:{dirs['base']}")

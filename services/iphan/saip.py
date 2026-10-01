import datetime
import os

from services.iphan._common import (
    build_output_dirs,
    download_file,
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
from services.iphan._saip_excel import SAIP_PF_EXCEL_NAME, write_saip_pf_excel
from services.iphan._saip_project_files import (
    fetch_saip_files_html,
    find_best_pf_planilha,
    parse_saip_files_html,
)
from services.iphan._wiki_backlog import fetch_backlog_html, filter_sprints_by_end_date
from services.iphan._wiki_download_saip import (
    download_saip_rows,
    download_sprint_attachments,
    download_sprint_pdfs,
)
from services.iphan._wiki_sprints_saip import (
    SAIP_SPRINTS_PDF_URL,
    SAIP_SPRINTS_WIKI_URL,
    collect_saip_data,
    parse_saip_sprints_index_html,
)
from utils.month_selector import MONTH_NAMES

PROJECT_KEY = "saip"
PROJECT_LABEL = "SAIP"
SPRINTS_PDF_NAME = "Sprints.pdf"


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
    pf_year = start_date.year
    pf_month = start_date.month
    month_label = MONTH_NAMES[pf_month - 1]

    dirs = build_output_dirs(PROJECT_KEY, month_label, include_pf_contagem=False)
    print(f"\n[{timestamp()}] Preparando evidências {PROJECT_LABEL}...")
    print(f"Período: {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}")
    print(f"Mês da planilha PF: {month_label}/{pf_year}")
    print(f"Pasta de saída: {dirs['base']}")

    print(f"\n[{timestamp()}] Lendo wiki Sprints...")
    sprints_html = fetch_backlog_html(session, SAIP_SPRINTS_WIKI_URL)
    all_sprints = parse_saip_sprints_index_html(sprints_html)
    matched_sprints = filter_sprints_by_end_date(all_sprints, start_date, end_date)
    sprint_numbers = {sprint.sprint_number for sprint in matched_sprints}

    print(f"[{timestamp()}] Sprints no período: {len(matched_sprints)} ({sorted(sprint_numbers)})")

    print(f"\n[{timestamp()}] Coletando itens das páginas de sprint...")
    rows, pages_by_sprint = collect_saip_data(session, matched_sprints)
    print(f"[{timestamp()}] Itens com wiki: {len(rows)}")

    sprint_pdf_ok, sprint_pdf_fail = download_sprint_pdfs(session, matched_sprints, dirs)

    attach_ok = 0
    attach_fail = 0
    for sprint in matched_sprints:
        page_data = pages_by_sprint.get(sprint.sprint_slug)
        if not page_data:
            continue
        ok, fail = download_sprint_attachments(session, sprint, page_data, dirs)
        attach_ok += ok
        attach_fail += fail

    wiki_ok, wiki_fail = download_saip_rows(session, rows, dirs)

    excel_dest = os.path.join(dirs["base"], SAIP_PF_EXCEL_NAME)
    print(f"\n[{timestamp()}] Gerando {SAIP_PF_EXCEL_NAME}...")
    excel_ok = write_saip_pf_excel(rows, excel_dest)

    print(f"\n[{timestamp()}] Listando arquivos do projeto...")
    files_html = fetch_saip_files_html(session)
    file_entries = parse_saip_files_html(files_html)
    pf_match = find_best_pf_planilha(file_entries, pf_year, pf_month, sprint_numbers)
    pf_ok = False
    if pf_match:
        pf_dest = os.path.join(dirs["base"], safe_filename(pf_match.filename))
        print(f"[{timestamp()}] Baixando planilha PF: {pf_match.filename}")
        pf_ok = download_file(
            session,
            pf_match.download_url,
            pf_dest,
            context=f"Planilha Contagem PF | {pf_match.filename}",
        )
    else:
        print(
            f"[{timestamp()}] WARN: Nenhuma Planilha Contagem PF encontrada "
            f"para {month_label}/{pf_year}."
        )

    sprints_dest = os.path.join(dirs["base"], SPRINTS_PDF_NAME)
    print(f"\n[{timestamp()}] Baixando {SPRINTS_PDF_NAME}...")
    sprints_ok = download_file(
        session,
        SAIP_SPRINTS_PDF_URL,
        sprints_dest,
        context=SPRINTS_PDF_NAME,
    )

    write_error_registry(dirs["base"])

    print(f"\n[{timestamp()}] Resumo:")
    print(f"  Sprint PDFs: {sprint_pdf_ok} ok, {sprint_pdf_fail} falha(s)")
    print(f"  Anexos sprint: {attach_ok} ok, {attach_fail} falha(s)")
    print(f"  Wiki PDFs: {wiki_ok} ok, {wiki_fail} falha(s)")
    print(f"  {SAIP_PF_EXCEL_NAME}: {'ok' if excel_ok else 'falha'}")
    print(f"  Planilha Contagem PF: {'ok' if pf_ok else 'falha ou não encontrada'}")
    print(f"  {SPRINTS_PDF_NAME}: {'ok' if sprints_ok else 'falha'}")
    print(f"  {error_registry_summary()}")
    print(f"\n[{timestamp()}] Fim! DIRETORIO_FINAL:{dirs['base']}")

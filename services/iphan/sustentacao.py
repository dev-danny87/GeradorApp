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
from services.iphan._sustentacao_files import (
    fetch_sustentacao_files_html,
    find_best_delivery_report,
    parse_sustentacao_files_html,
)
from utils.month_selector import MONTH_NAMES

PROJECT_KEY = "sustentacao"
PROJECT_LABEL = "SUSTENTAÇÃO"


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


def generate_evidences(session, app_state):
    set_app_run(True)

    if not session:
        print(f"[{timestamp()}] ERROR: Sessão inválida. Faça login primeiro.")
        return

    ok, message = validate_selection(app_state)
    if not ok:
        print(f"[{timestamp()}] ERROR: {message}")
        return

    cache = options_cache(app_state, PROJECT_KEY)
    start_date = cache["start_date"]
    year = start_date.year
    month = start_date.month
    month_label = MONTH_NAMES[month - 1]

    output_dir = build_output_dirs(PROJECT_KEY, include_pf_contagem=False)["base"]
    print(f"\n[{timestamp()}] Preparando relatório {PROJECT_LABEL}...")
    print(f"Mês selecionado: {month_label}/{year}")
    print(f"Pasta de saída: {output_dir}")

    print(f"\n[{timestamp()}] Listando arquivos do projeto...")
    files_html = fetch_sustentacao_files_html(session)
    entries = parse_sustentacao_files_html(files_html)
    print(f"[{timestamp()}] Arquivos encontrados: {len(entries)}")

    match = find_best_delivery_report(entries, year, month)
    if not match:
        print(
            f"[{timestamp()}] ERROR: Nenhum relatório de entregas encontrado "
            f"para {month_label}/{year}."
        )
        return

    dest_path = os.path.join(output_dir, safe_filename(match.filename))
    print(f"\n[{timestamp()}] Baixando: {match.filename}")
    download_ok = download_file(session, match.download_url, dest_path)

    print(f"\n[{timestamp()}] Resumo:")
    print(f"  Relatório: {'ok' if download_ok else 'falha'} ({match.filename})")
    print(f"\n[{timestamp()}] Fim! DIRETORIO_FINAL:{output_dir}")

"""
Stamp Jan–Oct 2026 onto copies of the ordered ai_tasks analyses and build
monthly PDFs plus one yearly file.

Original files under ./ai_tasks are only read.
"""

from __future__ import annotations

import datetime
import json
import os

from services.metrics_report.art_direction import fallback_direction
from services.metrics_report.pdf_report import write_metrics_pdf
from utils.app_config import ensure_task_manager_dirs, task_manager_dir
from utils.month_selector import MONTH_NAMES
from utils.output_paths import safe_segment
from utils.pdf_merger import merge_documents

AI_TASKS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "ai_tasks")

# Creation order starting at 08/10/2026 18:47. January through October 2026.
PERIOD_FILES = (
    (1, "ai_tasks_danilo.machado_2026-10-08_184714.json"),
    (2, "ai_tasks_danilo.machado_2026-10-08_193858.json"),
    (3, "ai_tasks_danilo.machado_2026-10-08_200650.json"),
    (4, "ai_tasks_danilo.machado_2026-10-08_202902.json"),
    (5, "ai_tasks_danilo.machado_2026-10-09_081644.json"),
    (6, "ai_tasks_danilo.machado_2026-10-09_083026.json"),
    (7, "ai_tasks_danilo.machado_2026-10-09_083716.json"),
    (8, "ai_tasks_danilo.machado_2026-10-09_090315.json"),
    (9, "ai_tasks_danilo.machado_2026-10-09_093600.json"),
    (10, "ai_tasks_danilo.machado_2026-10-09_094817.json"),
)

PROJECT = "SICOR"
YEAR = 2026
COVER = r"C:\Users\danilo.machado\Downloads\Capa_Relatorio_Desenvolvimento_horas.pdf"
CLOSE = r"C:\Users\danilo.machado\Downloads\Fechamento_Relatorio_Desenvolvimento_horas.pdf"


def period_payload(month: int, year: int = YEAR) -> dict:
    return {
        "year": year,
        "month": month,
        "label": f"{MONTH_NAMES[month - 1]} {year}",
    }


def period_for_source(source: str, year: int = YEAR) -> dict | None:
    """Map an ai_tasks filename to its January–October period. None if unmapped."""
    name = os.path.basename(source or "")
    for month, filename in PERIOD_FILES:
        if name == filename:
            return period_payload(month, year)
    return None


def stamp_copy(payload: dict, month: int) -> dict:
    period = period_payload(month)
    work_date = f"{YEAR}-{month:02d}-01"
    copied = dict(payload)
    copied["period"] = period
    tasks = []
    for task in payload.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        item = dict(task)
        item["period"] = dict(period)
        item["work_date"] = work_date
        tasks.append(item)
    copied["tasks"] = tasks
    return copied


def report_root() -> str:
    ensure_task_manager_dirs()
    return os.path.join(
        str(task_manager_dir()),
        "relatorios",
        "metricas",
        safe_segment(PROJECT),
    )


def month_folder(month: int) -> str:
    name = f"{YEAR}-{month:02d}_{MONTH_NAMES[month - 1]}"
    return os.path.join(report_root(), name)


def _log(message: str) -> None:
    text = f"[RELATÓRIO] {message}"
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("cp1252", errors="replace").decode("cp1252"), flush=True)


def apply_mapping(*, generate_pdfs: bool = True) -> dict:
    """Write period copies and, when requested, monthly plus yearly PDFs."""
    root = report_root()
    os.makedirs(root, exist_ok=True)
    month_pdfs: list[str] = []
    all_tasks: list[dict] = []
    art = fallback_direction()

    for month, filename in PERIOD_FILES:
        source = os.path.abspath(os.path.join(AI_TASKS_DIR, filename))
        _log(f"Mês {month}/10 — lendo {filename}")
        with open(source, "r", encoding="utf-8") as handle:
            original = json.load(handle)
        stamped = stamp_copy(original, month)
        folder = month_folder(month)
        os.makedirs(folder, exist_ok=True)
        tasks_path = os.path.join(folder, "tarefas.json")
        meta_path = os.path.join(folder, "meta.json")
        pdf_path = os.path.join(folder, "periodo.pdf")
        with open(tasks_path, "w", encoding="utf-8") as handle:
            json.dump(stamped, handle, ensure_ascii=False, indent=2)
        meta = {
            "kind": "periodo",
            "project": PROJECT,
            "period": period_payload(month),
            "source_file": source,
            "task_count": len(stamped["tasks"]),
            "tasks_copy": os.path.abspath(tasks_path),
            "pdf": os.path.abspath(pdf_path),
            "written_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(meta, handle, ensure_ascii=False, indent=2)
        all_tasks.extend(stamped["tasks"])
        if generate_pdfs and os.path.isfile(pdf_path) and os.path.getsize(pdf_path) > 0:
            _log(f"Mês {month}/10 — PDF já existe, mantido: {pdf_path}")
            month_pdfs.append(pdf_path)
        elif generate_pdfs:
            _log(f"Mês {month}/10 — gerando {pdf_path}")
            write_metrics_pdf(
                pdf_path,
                stamped["tasks"],
                PROJECT,
                art=art,
                body="months",
                on_progress=_log,
            )
            month_pdfs.append(pdf_path)

    yearly_dir = os.path.join(root, f"{YEAR}_anual")
    os.makedirs(yearly_dir, exist_ok=True)
    year_body = os.path.join(yearly_dir, "ano.pdf")
    yearly_pdf = os.path.join(yearly_dir, "anual.pdf")
    if generate_pdfs:
        _log("Gerando página anual")
        write_metrics_pdf(
            year_body,
            all_tasks,
            PROJECT,
            art=art,
            body="year",
            on_progress=_log,
        )
        parts = []
        if os.path.isfile(COVER):
            parts.append(COVER)
        parts.append(year_body)
        parts.extend(month_pdfs)
        if os.path.isfile(CLOSE):
            parts.append(CLOSE)
        _log(f"Unindo {len(parts)} PDF(s) em {yearly_pdf}")
        merge_documents(parts, yearly_pdf)
    yearly_meta = {
        "kind": "anual",
        "project": PROJECT,
        "year": YEAR,
        "order": "capa, pagina anual, meses de janeiro a outubro, encerramento",
        "months": [period_payload(month) for month, _name in PERIOD_FILES],
        "month_pdfs": [os.path.abspath(path) for path in month_pdfs],
        "pdf": os.path.abspath(yearly_pdf),
        "task_count": len(all_tasks),
        "written_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    with open(os.path.join(yearly_dir, "meta.json"), "w", encoding="utf-8") as handle:
        json.dump(yearly_meta, handle, ensure_ascii=False, indent=2)
    _log(f"Pronto: {yearly_pdf}")
    return {"root": root, "yearly_pdf": yearly_pdf, "months": month_pdfs}


def build_named_project(project: str) -> str:
    """Write month folders and a consolidated PDF for a project name from the mapped analyses."""
    from services.metrics_report.art_direction import fallback_direction
    from services.metrics_report.period_reports import consolidate_period_reports, write_period_folders

    tasks: list[dict] = []
    for _month, filename in PERIOD_FILES:
        source = os.path.abspath(os.path.join(AI_TASKS_DIR, filename))
        with open(source, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        period = period_for_source(filename)
        _log(f"Origem {filename} -> {period['label']}")
        for task in payload.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            item = dict(task)
            item["period"] = dict(period)
            item["date_precision"] = "month"
            item["work_date"] = f"{period['year']}-{int(period['month']):02d}-01"
            tasks.append(item)
    reports = write_period_folders(project, tasks)
    _log("Pastas: " + ", ".join(item["label"] for item in reports))
    return consolidate_period_reports(
        project,
        reports,
        cover_pdf=COVER if os.path.isfile(COVER) else None,
        close_pdf=CLOSE if os.path.isfile(CLOSE) else None,
        on_progress=_log,
        art=fallback_direction(),
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        print(build_named_project(sys.argv[1]), flush=True)
    else:
        apply_mapping(generate_pdfs=True)

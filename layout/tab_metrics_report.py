"""Tab that builds a metrics PDF from selected banco de horas tasks."""

from __future__ import annotations

import os
import shutil
import traceback
from threading import Thread
from urllib.parse import unquote, urlparse

import flet as ft

from layout.task_hour_list import TaskHourListView
from services.metrics_report.apply_sicor_periods import period_for_source
from services.metrics_report.period_reports import (
    consolidate_period_reports,
    list_period_reports,
    write_period_folders,
)
from utils.banco_horas_store import list_banco_batches, totals
from utils.output_paths import build_metrics_report_path, safe_segment
from utils.redmine_task_defaults import redmine_task_defaults
from utils.task_hour_selection import ensure_task_ids, sum_task_hours


def filesystem_save_path(result) -> str | None:
    """Turn a FilePicker save result into a local path Python can write."""
    if result is None:
        return None
    if isinstance(result, bytes):
        result = result.decode("utf-8", errors="replace")
    if not isinstance(result, str):
        nested = getattr(result, "path", None)
        if isinstance(result, dict):
            nested = result.get("path") or result.get("file_path")
        result = nested if isinstance(nested, str) else ""
    text = result.strip()
    if not text or text.lower() in {"null", "none"}:
        return None
    if text.startswith("file:"):
        parsed = urlparse(text)
        text = unquote(parsed.path or "")
        if os.name == "nt" and len(text) >= 3 and text[0] == "/" and text[2] == ":":
            text = text[1:]
    return text or None


def create_metrics_report_tab(
        page,
        app_state,
        set_auth,
        sync_callbacks,
        banco_listeners=None,
        metrics_listeners=None,
):
    lbl_logged_in = ft.Text("", color="green", weight=ft.FontWeight.BOLD, size=14)
    lbl_status = ft.Text("", visible=False, weight=ft.FontWeight.BOLD)
    progress_ring = ft.ProgressRing(visible=False, width=20, height=20)
    lbl_totals = ft.Text("", size=14, weight=ft.FontWeight.BOLD, color="purple")
    lbl_cover = ft.Text("Nenhuma capa", size=12, color=ft.Colors.GREY_700)
    lbl_close = ft.Text("Nenhum encerramento", size=12, color=ft.Colors.GREY_700)

    defaults = redmine_task_defaults(app_state.get("user"))
    txt_projeto = ft.TextField(
        label="Projeto",
        width=350,
        value=defaults["projeto"],
    )

    cover = {"path": None}
    close = {"path": None}
    ready = {"path": None}
    generating = {"on": False}
    task_lists: list[TaskHourListView] = []
    period_rows: list[tuple[dict, ft.Checkbox]] = []
    period_column = ft.Column(spacing=4, tight=True)

    btn_refresh = ft.ElevatedButton("Atualizar", icon=ft.Icons.REFRESH)
    btn_all = ft.ElevatedButton("Selecionar todas", icon=ft.Icons.DONE_ALL)
    btn_none = ft.ElevatedButton("Limpar seleção", icon=ft.Icons.CLEAR_ALL)
    btn_generate = ft.ElevatedButton(
        "Gerar relatório PDF",
        icon=ft.Icons.PICTURE_AS_PDF,
        bgcolor="blue_700",
        color="white",
        disabled=True,
    )
    btn_save = ft.ElevatedButton("Salvar PDF", icon=ft.Icons.SAVE, disabled=True)
    btn_cover = ft.ElevatedButton("Escolher capa", icon=ft.Icons.UPLOAD_FILE)
    btn_cover_clear = ft.TextButton("Limpar capa")
    btn_close = ft.ElevatedButton("Escolher encerramento", icon=ft.Icons.UPLOAD_FILE)
    btn_close_clear = ft.TextButton("Limpar encerramento")

    batch_column = ft.Column(spacing=10, tight=True)

    def _page():
        try:
            return view.page
        except RuntimeError:
            return None

    def _refresh_ui():
        current = _page()
        if current:
            current.update()

    def show_status(text: str, color: str):
        lbl_status.value = text
        lbl_status.color = color
        lbl_status.visible = bool(text)

    def _selected_tasks() -> list[dict]:
        selected = []
        for task_list in task_lists:
            selected.extend(dict(task) for task in task_list.selected_tasks())
        return selected

    def _update_buttons():
        busy = generating["on"]
        has_selection = bool(_selected_tasks()) or any(checkbox.value for _item, checkbox in period_rows)
        btn_generate.disabled = busy or not has_selection
        btn_save.disabled = busy or not ready["path"]
        btn_refresh.disabled = busy
        btn_all.disabled = busy
        btn_none.disabled = busy
        btn_cover.disabled = busy
        btn_close.disabled = busy
        progress_ring.visible = busy

    def _on_selection(_view):
        if not generating["on"]:
            btn_generate.disabled = not _selected_tasks()

    def refresh_lists(e=None):
        task_lists.clear()
        batch_column.controls.clear()
        summary = totals()
        lbl_totals.value = (
            f"Total no banco: {summary['total_hours']:g}h em {summary['task_count']} tarefa(s) "
            f"({summary['batch_count']} arquivo(s))"
        )
        entries = list_banco_batches()
        if not entries:
            batch_column.controls.append(
                ft.Text("Nenhuma tarefa no banco de horas.", italic=True, color=ft.Colors.GREY_600)
            )
            _update_buttons()
            _refresh_ui()
            return

        for batch_index, entry in enumerate(entries, start=1):
            prefix = f"lote{batch_index:03d}"
            tasks = ensure_task_ids(entry.get("tasks") or [], prefix=prefix)
            if not tasks:
                continue
            period = period_for_source(entry.get("source_analysis") or "")
            for task in tasks:
                if period and not task.get("work_date") and not isinstance(task.get("period"), dict):
                    task["period"] = dict(period)
                    task["date_precision"] = "month"
                    task["work_date"] = f"{period['year']}-{int(period['month']):02d}-01"
                elif task.get("work_date") or isinstance(task.get("period"), dict):
                    pass
                else:
                    task["_report_date"] = entry.get("saved_at") or ""
            lote_title = entry.get("label") or entry.get("filename") or "Lote"
            if period:
                lote_title = f"{period['label']} — {lote_title}"
            task_list = TaskHourListView(
                title=lote_title,
                on_selection_change=_on_selection,
                show_budget=False,
                show_lote_select=True,
                initially_expanded=False,
            )
            task_list.set_tasks(tasks)
            task_list.root.visible = True
            task_lists.append(task_list)
            batch_column.controls.append(task_list.root)

        refresh_periods()
        _update_buttons()
        _refresh_ui()

    def refresh_periods(e=None):
        period_rows.clear()
        period_column.controls.clear()
        project = (txt_projeto.value or "").strip()
        reports = list_period_reports(project) if project else []
        if not reports:
            period_column.controls.append(
                ft.Text(
                    "Nenhum relatório mensal com período salvo para este projeto.",
                    size=12,
                    italic=True,
                    color=ft.Colors.GREY_600,
                )
            )
            return
        for item in reports:
            checkbox = ft.Checkbox(value=True, on_change=_on_selection)
            period_rows.append((item, checkbox))
            period_column.controls.append(
                ft.Row(
                    [
                        checkbox,
                        ft.Text(
                            f"{item['label']} — {item['task_count']} tarefa(s)",
                            expand=True,
                        ),
                    ],
                    spacing=8,
                )
            )
        _update_buttons()
        _refresh_ui()

    def _checked_periods() -> list[dict]:
        return [item for item, checkbox in period_rows if checkbox.value]

    def handle_select_all(e):
        for task_list in task_lists:
            task_list.select_all()
        count = len(_selected_tasks())
        hours = sum_task_hours(_selected_tasks())
        show_status(f"Selecionadas {count} tarefa(s) em todos os lotes — {hours:g}h.", "blue")
        _update_buttons()
        _refresh_ui()

    def handle_clear_selection(e):
        for task_list in task_lists:
            task_list.clear_selection()
        show_status("Seleção limpa em todos os lotes.", "blue")
        _update_buttons()
        _refresh_ui()

    file_picker = ft.FilePicker()
    save_dialog = ft.FilePicker()
    page.overlay.append(file_picker)
    page.overlay.append(save_dialog)

    async def _pick_pdf(title: str):
        return await file_picker.pick_files(
            dialog_title=title,
            allow_multiple=False,
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["pdf"],
        )

    async def pick_cover(e):
        files = await _pick_pdf("PDF de capa")
        if not files:
            return
        if not files[0].path:
            show_status("Não foi possível ler o caminho da capa.", "red")
            _refresh_ui()
            return
        cover["path"] = files[0].path
        lbl_cover.value = files[0].name
        _refresh_ui()

    async def pick_close(e):
        files = await _pick_pdf("PDF de encerramento")
        if not files:
            return
        if not files[0].path:
            show_status("Não foi possível ler o caminho do encerramento.", "red")
            _refresh_ui()
            return
        close["path"] = files[0].path
        lbl_close.value = files[0].name
        _refresh_ui()

    def clear_cover(e):
        cover["path"] = None
        lbl_cover.value = "Nenhuma capa"
        _refresh_ui()

    def clear_close(e):
        close["path"] = None
        lbl_close.value = "Nenhum encerramento"
        _refresh_ui()

    def _write_saved_pdf(source: str, dest: str) -> None:
        if not dest.lower().endswith(".pdf"):
            dest_path = dest + ".pdf"
        else:
            dest_path = dest
        folder = os.path.dirname(dest_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        if not os.path.isfile(dest_path) or os.path.getsize(dest_path) == 0:
            shutil.copy2(source, dest_path)
        if not os.path.isfile(dest_path) or os.path.getsize(dest_path) == 0:
            raise OSError(f"O arquivo não foi gravado em {dest_path}")
        show_status(f"Cópia salva em: {dest_path}", "green")
        page.open(ft.SnackBar(ft.Text(f"Cópia salva em: {dest_path}"), bgcolor="green"))

    async def prompt_save(e=None):
        source = ready["path"]
        if not source or not os.path.isfile(source):
            show_status("Gere o relatório antes de salvar.", "red")
            _refresh_ui()
            return
        projeto = txt_projeto.value or "projeto"
        try:
            with open(source, "rb") as handle:
                payload = handle.read()
            chosen = await save_dialog.save_file(
                dialog_title="Salvar relatório",
                file_name=f"Relatorio_Metricas_{safe_segment(projeto)}.pdf",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["pdf"],
                src_bytes=payload,
            )
            dest = filesystem_save_path(chosen)
            if not dest:
                show_status(
                    f"Relatório já está em: {source}. A cópia foi cancelada.",
                    "blue",
                )
                return
            _write_saved_pdf(source, dest)
        except Exception as err:
            show_status(f"Não foi possível salvar o arquivo: {err}", "red")
        finally:
            _refresh_ui()

    def _validate_optional(path: str | None, label: str) -> str | None:
        if not path:
            return None
        if not os.path.isfile(path):
            raise FileNotFoundError(f"O PDF de {label} não foi encontrado.")
        if not path.lower().endswith(".pdf"):
            raise ValueError(f"O arquivo de {label} precisa ser um PDF.")
        return path

    def handle_generate(e):
        if generating["on"]:
            return
        periods = _checked_periods()
        selected = _selected_tasks()
        if not periods and not selected:
            show_status("Marque relatórios mensais ou selecione tarefas do banco.", "red")
            _refresh_ui()
            return
        project = (txt_projeto.value or "").strip()
        if not project:
            show_status("Selecione o projeto.", "red")
            _refresh_ui()
            return
        try:
            cover_pdf = _validate_optional(cover["path"], "capa")
            close_pdf = _validate_optional(close["path"], "encerramento")
        except (OSError, ValueError) as err:
            show_status(str(err), "red")
            _refresh_ui()
            return

        hours = sum_task_hours(selected) if selected else 0
        generating["on"] = True
        _update_buttons()
        if periods:
            show_status(
                f"Gerando {len(periods)} mês(es): capa, página anual e relatórios mensais.",
                "blue",
            )
        else:
            show_status(
                f"Gerando relatório de {len(selected)} tarefa(s) ({hours:g}h). Nenhuma hora será consumida.",
                "blue",
            )
        _refresh_ui()

        def on_progress(message: str):
            line = f"[RELATÓRIO] {message}"
            print(line)
            show_status(message, "blue")
            _refresh_ui()

        def bg_generate():
            dest_path = build_metrics_report_path(project)
            try:
                if periods:
                    dest_path = consolidate_period_reports(
                        project,
                        periods,
                        cover_pdf=cover_pdf,
                        close_pdf=close_pdf,
                        on_progress=on_progress,
                    )
                    art = None
                else:
                    art = None
                    reports = write_period_folders(project, selected)
                    on_progress(
                        "Períodos gravados: "
                        + ", ".join(item["label"] for item in reports)
                    )
                    dest_path = consolidate_period_reports(
                        project,
                        reports,
                        cover_pdf=cover_pdf,
                        close_pdf=close_pdf,
                        on_progress=on_progress,
                    )
            except Exception as err:
                print(f"[RELATÓRIO] Falha na geração: {err}")
                traceback.print_exc()
                if os.path.isfile(dest_path):
                    try:
                        size = os.path.getsize(dest_path)
                    except OSError:
                        size = 0
                    if size == 0:
                        try:
                            os.remove(dest_path)
                        except OSError:
                            pass
                show_status(f"Falha ao gerar o relatório: {err}", "red")
                return
            ready["path"] = os.path.abspath(dest_path)
            note = ""
            if art is not None and art.used_fallback:
                note = " Visual padrão: a IA não respondeu."
            show_status(
                f"Relatório salvo em: {ready['path']}.{note} Salvar PDF faz uma cópia.",
                "green",
            )
            print(f"[RELATÓRIO] Pronto: {ready['path']}")

        def runner():
            try:
                bg_generate()
            except Exception as err:
                print(f"[RELATÓRIO] Erro inesperado: {err}")
                traceback.print_exc()
                show_status(f"Falha ao gerar o relatório: {err}", "red")
            finally:
                generating["on"] = False
                _update_buttons()
                _refresh_ui()

        Thread(target=runner, daemon=True).start()

    txt_projeto.on_blur = refresh_periods
    txt_projeto.on_submit = refresh_periods
    btn_refresh.on_click = refresh_lists
    btn_all.on_click = handle_select_all
    btn_none.on_click = handle_clear_selection
    btn_generate.on_click = handle_generate
    btn_save.on_click = prompt_save
    btn_cover.on_click = pick_cover
    btn_cover_clear.on_click = clear_cover
    btn_close.on_click = pick_close
    btn_close_clear.on_click = clear_close

    user_header = ft.Row(
        [
            ft.Icon(ft.Icons.PERSON, color="green", size=20),
            lbl_logged_in,
            ft.IconButton(
                icon=ft.Icons.LOGOUT,
                icon_color="red",
                icon_size=20,
                tooltip="Sair da conta",
                on_click=lambda e: set_auth(None, None, False),
            ),
        ],
        alignment=ft.MainAxisAlignment.END,
    )

    wrapper = ft.Container(
        content=ft.Column(
            [
                ft.Text("Relatório de métricas", weight=ft.FontWeight.BOLD, size=15, color="purple"),
                ft.Text(
                    "Gerar usa os meses marcados: capa, página anual e cada PDF mensal. "
                    "Salvar PDF faz uma cópia. O banco de horas não é consumido.",
                    size=12,
                    color=ft.Colors.GREY_700,
                ),
                lbl_totals,
                txt_projeto,
                ft.Row(
                    [ft.Text("Capa (PDF)", weight=ft.FontWeight.BOLD, size=12), lbl_cover, btn_cover, btn_cover_clear],
                    wrap=True,
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    [
                        ft.Text("Encerramento (PDF)", weight=ft.FontWeight.BOLD, size=12),
                        lbl_close,
                        btn_close,
                        btn_close_clear,
                    ],
                    wrap=True,
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    [btn_refresh, btn_all, btn_none, btn_generate, btn_save, progress_ring],
                    wrap=True,
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Text("Relatórios mensais salvos", weight=ft.FontWeight.BOLD, size=13),
                period_column,
                ft.Divider(),
                batch_column,
            ],
            spacing=10,
            tight=True,
        ),
        padding=15,
        border=ft.border.all(1, ft.Colors.PURPLE_300),
        border_radius=10,
    )

    view = ft.Column(
        [
            user_header,
            ft.Text("Relatório", size=16, weight=ft.FontWeight.BOLD),
            wrapper,
            lbl_status,
        ],
        alignment=ft.MainAxisAlignment.START,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=15,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )

    def sync_ui():
        if app_state.get("session"):
            lbl_logged_in.value = app_state["user"]
            defaults_now = redmine_task_defaults(app_state.get("user"))
            if not txt_projeto.value:
                txt_projeto.value = defaults_now["projeto"]
        refresh_lists()

    sync_callbacks.append(sync_ui)
    if banco_listeners is not None:
        banco_listeners.append(refresh_lists)
    if metrics_listeners is not None:
        metrics_listeners.append(refresh_lists)
    sync_ui()

    return ft.Tab(
        text="Relatório",
        icon=ft.Icons.BAR_CHART,
        content=ft.Container(content=view, padding=20, expand=True),
    )

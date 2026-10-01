# tab_ai_analysis.py
import flet as ft
import os
import datetime
import json
from threading import Thread, Event

from services.ai_api_request import (
    CHECKPOINT_FILENAME,
    MODEL_CONFIGS,
    analyze_diffs_grouped_with_claude,
)
from diff_task_automation import create_ai_redmine_tasks
from redmine_mappings import (
    SYSTEM_OPTIONS,
    ORGAN_OPTIONS,
    PROJECT_FILTER_OPTIONS,
    ROLE_OPTIONS,
    USER_OPTIONS,
)
from layout.task_hour_list import TaskHourListView
from utils.ai_tasks_store import list_saved_results, load_tasks, save_results, save_fechamento
from utils.banco_horas_store import save_banco_batch
from utils.commit_metadata import strip_urls_from_description
from utils.fechamento_builder import (
    build_fechamento_payload,
    prepare_tasks_with_commits,
)
from utils.month_selector import (
    apply_month_to_date_pickers,
    create_month_shortcut_dropdown,
    current_month_key,
    month_bounds,
)
from utils.redmine_task_defaults import get_min_task_hours, redmine_task_defaults
from utils.redmine_version import (
    default_open_version_id,
    fetch_open_versions,
    get_dynamic_version,
)
from utils.task_hour_selection import ensure_task_ids, sum_task_hours
from utils.ui_components import DatePickerField

DIFFS_ROOT = os.path.join(".", "diffs")


def _diff_label(folder_path: str, file_path: str) -> str:
    """Top-level files keep the bare filename so an existing checkpoint still matches."""
    relative = os.path.relpath(file_path, folder_path).replace("\\", "/")
    if os.path.dirname(relative) in ("", "."):
        return os.path.basename(relative)
    return relative


def _list_diff_labels(folder_path: str) -> list[str]:
    labels: list[str] = []
    if not os.path.isdir(folder_path):
        return labels
    for root, dirs, files in os.walk(folder_path):
        dirs[:] = sorted(name for name in dirs if not name.startswith("."))
        for filename in sorted(files):
            if filename.endswith(".txt"):
                labels.append(_diff_label(folder_path, os.path.join(root, filename)))
    return labels


def _checkpoint_done_labels(folder_path: str) -> set[str]:
    checkpoint_path = os.path.join(folder_path, CHECKPOINT_FILENAME)
    if not os.path.isfile(checkpoint_path):
        return set()
    try:
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(data, dict):
        return set()
    processed = [str(label) for label in data.get("processed_labels", []) if label]
    unit_tasks = [item for item in data.get("unit_tasks", []) if isinstance(item, dict)]
    if len(processed) != len(unit_tasks):
        return set()
    return set(processed)


def _collect_diff_items(folder_path: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    if not os.path.isdir(folder_path):
        return items
    for root, dirs, files in os.walk(folder_path):
        dirs[:] = sorted(name for name in dirs if not name.startswith("."))
        for filename in sorted(files):
            if not filename.endswith(".txt"):
                continue
            file_path = os.path.join(root, filename)
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                items.append((_diff_label(folder_path, file_path), content))
    items.sort(key=lambda item: item[0])
    return items


def _dropdown_from_mapping(label: str, mapping: dict, default_value: str, width: int = 350) -> ft.Dropdown:
    return ft.Dropdown(
        label=label,
        width=width,
        options=[ft.dropdown.Option(key=v, text=k) for k, v in mapping.items()],
        value=default_value,
    )


def create_ai_analysis_tab(
        app_state,
        set_auth,
        sync_callbacks,
        diffs_listeners=None,
        fechamento_listeners=None,
        folder_refresh_listeners=None,
        banco_listeners=None,
):
    lbl_logged_in = ft.Text("", color="green", weight=ft.FontWeight.BOLD, size=14)
    lbl_status = ft.Text("", visible=False, weight=ft.FontWeight.BOLD)
    progress_ring = ft.ProgressRing(visible=False, width=20, height=20)

    stop_event = Event()
    current_analysis_path: list[str | None] = [None]
    current_source_folder: list[str | None] = [None]

    dropdown_folders = ft.Dropdown(label="Pasta de Diffs Exportados", width=520)

    dropdown_model = ft.Dropdown(
        label="Modelo de IA",
        width=350,
        options=[
            ft.dropdown.Option(key=model_key, text=model_key)
            for model_key in MODEL_CONFIGS.keys()
        ],
        value=list(MODEL_CONFIGS.keys())[0],
    )

    btn_process_ai = ft.ElevatedButton("Processar com IA", icon=ft.Icons.AUTO_AWESOME, color="white", bgcolor="purple")
    btn_stop_ai = ft.ElevatedButton(
        "Parar",
        icon=ft.Icons.STOP_CIRCLE,
        color="white",
        bgcolor="red",
        visible=False,
        tooltip="Interrompe o processamento antes do próximo arquivo",
    )

    dropdown_results = ft.Dropdown(label="Análise Salva", width=520)
    btn_create_redmine_tasks = ft.ElevatedButton(
        "Gerar Tarefas no Redmine",
        icon=ft.Icons.CLOUD_UPLOAD,
        bgcolor="blue_700",
        color="white",
        visible=False,
    )

    hoje = datetime.datetime.now().date()
    inicio_mes, fim_mes = month_bounds(hoje)
    defaults = redmine_task_defaults(app_state.get("user"))

    date_start = DatePickerField(
        label="Data de Início (Sprint)",
        default_date=inicio_mes,
        width=200,
        icon=ft.Icons.CALENDAR_TODAY,
    )
    date_due = DatePickerField(
        label="Data Prevista (Sprint)",
        default_date=fim_mes,
        width=200,
        icon=ft.Icons.EVENT,
    )

    def on_month_change(e):
        if not dropdown_month.value:
            return
        apply_month_to_date_pickers(dropdown_month.value, date_start, date_due)
        try:
            if date_start.page:
                date_start.update()
                date_due.update()
        except RuntimeError:
            pass

    dropdown_month = create_month_shortcut_dropdown(
        on_month_change,
        value=current_month_key(hoje),
    )

    dropdown_versao = ft.Dropdown(
        label="Versão",
        width=350,
        options=[],
        value=None,
        hint_text="Faça login para carregar as versões abertas",
    )

    dropdown_sistema = _dropdown_from_mapping("Sistema", SYSTEM_OPTIONS, defaults["sistema"])
    dropdown_orgao = _dropdown_from_mapping("Órgão solicitante", ORGAN_OPTIONS, defaults["orgao"])
    dropdown_atribuicao = _dropdown_from_mapping(
        "Atribuição Catálogo - Desenv", ROLE_OPTIONS, defaults["atribuicao"]
    )
    dropdown_projeto = _dropdown_from_mapping(
        "Projeto Vinculado", PROJECT_FILTER_OPTIONS, defaults["projeto"]
    )
    dropdown_desenvolvedor = ft.Dropdown(
        label="Desenvolvedor",
        width=350,
        options=[ft.dropdown.Option(key=v, text=k) for k, v in USER_OPTIONS.items()],
        value=defaults.get("desenvolvedor_id"),
    )

    task_list = TaskHourListView(title="Tarefas estimadas (clique para expandir)")

    wrapper_ai_box = ft.Container(
        content=ft.Column([
            ft.Text("Análise Inteligente e Geração de Tarefas", weight=ft.FontWeight.BOLD, size=15, color="purple"),
            ft.Row(
                [dropdown_model, dropdown_folders, dropdown_atribuicao],
                alignment=ft.MainAxisAlignment.START,
                wrap=True,
            ),
            ft.Row([btn_process_ai, btn_stop_ai], alignment=ft.MainAxisAlignment.START, wrap=True),
            ft.Divider(),
            ft.Row([dropdown_results], alignment=ft.MainAxisAlignment.START, wrap=True),
            task_list.root,
            ft.Row([btn_create_redmine_tasks], alignment=ft.MainAxisAlignment.START, wrap=True),
            ft.Text("Campos Redmine (tarefa pai e subtarefas)", weight=ft.FontWeight.BOLD, size=13),
            ft.Row([dropdown_month], alignment=ft.MainAxisAlignment.START),
            ft.Row([date_start, date_due], alignment=ft.MainAxisAlignment.START, spacing=20, tight=True),
            ft.Row([dropdown_versao], alignment=ft.MainAxisAlignment.START),
            ft.Row([dropdown_sistema, dropdown_orgao], alignment=ft.MainAxisAlignment.START, wrap=True),
            ft.Row([dropdown_projeto, dropdown_desenvolvedor], alignment=ft.MainAxisAlignment.START, wrap=True),
        ]),
        padding=15,
        border=ft.border.all(1, ft.Colors.PURPLE_300),
        border_radius=10,
    )

    user_header = ft.Row([
        ft.Icon(ft.Icons.PERSON, color="green", size=20),
        lbl_logged_in,
        ft.IconButton(
            icon=ft.Icons.LOGOUT,
            icon_color="red",
            icon_size=20,
            tooltip="Sair da conta",
            on_click=lambda e: set_auth(None, None, False),
        ),
    ], alignment=ft.MainAxisAlignment.END)

    ai_view = ft.Column([
        user_header,
        ft.Text("Análise de Diffs com IA", size=16, weight=ft.FontWeight.BOLD),
        ft.Row([progress_ring], alignment=ft.MainAxisAlignment.CENTER),
        wrapper_ai_box,
        lbl_status,
    ], alignment=ft.MainAxisAlignment.START, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=15, expand=True,
        scroll=ft.ScrollMode.AUTO)

    def _refresh_ui():
        try:
            page = ai_view.page
        except RuntimeError:
            return
        if page:
            page.update()

    def show_status(text: str, color: str):
        lbl_status.value = text
        lbl_status.color = color
        lbl_status.visible = True

    def _notify_banco_listeners():
        for listener in banco_listeners or []:
            try:
                listener()
            except Exception as ex:
                print(f"[BANCO] Listener falhou: {ex}")

    def _apply_field_defaults():
        current_defaults = redmine_task_defaults(app_state.get("user"))
        agora = datetime.datetime.now().date()
        inicio, fim = month_bounds(agora)
        dropdown_month.value = current_month_key(agora)
        date_start.set_date(inicio)
        date_due.set_date(fim)
        dropdown_sistema.value = current_defaults["sistema"]
        dropdown_orgao.value = current_defaults["orgao"]
        dropdown_atribuicao.value = current_defaults["atribuicao"]
        dropdown_projeto.value = current_defaults["projeto"]
        dropdown_desenvolvedor.value = current_defaults.get("desenvolvedor_id")

    def _apply_versions(versions: list[dict], preferred_id: str | None = None):
        previous = preferred_id or dropdown_versao.value
        dropdown_versao.options = [
            ft.dropdown.Option(key=v["id"], text=v["name"]) for v in versions
        ]
        available_ids = {v["id"] for v in versions}
        if previous and previous in available_ids:
            dropdown_versao.value = previous
        else:
            dropdown_versao.value = default_open_version_id(versions)
        dropdown_versao.hint_text = None if versions else "Nenhuma versão aberta encontrada"
        try:
            if dropdown_versao.page:
                dropdown_versao.page.update()
            else:
                dropdown_versao.update()
        except RuntimeError:
            pass
        except Exception:
            pass

    def _load_open_versions():
        session = app_state.get("session")
        if not session:
            return
        previous = dropdown_versao.value
        versions = fetch_open_versions(session)
        if not versions:
            fallback_id = get_dynamic_version()
            versions = [{"id": fallback_id, "name": f"Versão {fallback_id} (fallback)"}]
            print(f"[VERSÃO] Usando fallback get_dynamic_version()={fallback_id}")
        _apply_versions(versions, preferred_id=previous)

    def _show_tasks_from_payload(payload: dict | list, results_path: str | None = None):
        if isinstance(payload, dict):
            tasks = payload.get("tasks") or []
            current_source_folder[0] = payload.get("source_diff_folder") or None
            if payload.get("atribuicao_catalogo"):
                dropdown_atribuicao.value = payload["atribuicao_catalogo"]
        else:
            tasks = payload if isinstance(payload, list) else []
            current_source_folder[0] = None

        if not isinstance(tasks, list):
            tasks = []
        tasks = ensure_task_ids(tasks)
        current_analysis_path[0] = results_path
        task_list.set_tasks(tasks)
        btn_create_redmine_tasks.visible = bool(tasks)
        total = sum_task_hours(tasks)
        if tasks:
            show_status(f"{len(tasks)} tarefa(s) carregada(s) — total {total:g}h.", "green")

    def refresh_saved_results(select_path: str = None):
        entries = list_saved_results()
        dropdown_results.options.clear()
        for entry in entries:
            dropdown_results.options.append(
                ft.dropdown.Option(key=entry["path"], text=entry["label"])
            )

        if entries:
            if select_path and any(entry["path"] == select_path for entry in entries):
                dropdown_results.value = select_path
            elif dropdown_results.value not in [entry["path"] for entry in entries]:
                dropdown_results.value = entries[0]["path"]
            _load_selected_analysis()
        else:
            dropdown_results.value = None
            task_list.clear()
            btn_create_redmine_tasks.visible = False
            current_analysis_path[0] = None

    def _load_selected_analysis(e=None):
        results_path = dropdown_results.value
        if not results_path:
            task_list.clear()
            btn_create_redmine_tasks.visible = False
            return
        try:
            with open(results_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            _show_tasks_from_payload(payload, results_path)
        except Exception as ex:
            try:
                tasks = load_tasks(results_path)
                _show_tasks_from_payload({"tasks": tasks}, results_path)
            except Exception:
                show_status(f"Falha ao carregar análise: {ex}", "red")
                task_list.clear()
                btn_create_redmine_tasks.visible = False
        _refresh_ui()

    dropdown_results.on_change = _load_selected_analysis

    def refresh_ai_folders():
        dropdown_folders.options.clear()
        previous = dropdown_folders.value
        dropdown_folders.value = None

        if not os.path.exists(DIFFS_ROOT):
            return

        folders = [f for f in os.listdir(DIFFS_ROOT) if os.path.isdir(os.path.join(DIFFS_ROOT, f))]
        if not folders:
            return

        for folder in sorted(folders, reverse=True):
            folder_path = os.path.join(DIFFS_ROOT, folder)
            labels = _list_diff_labels(folder_path)
            done = _checkpoint_done_labels(folder_path)
            already = sum(1 for label in labels if label in done)
            if labels:
                display_text = f"{folder} ({already}/{len(labels)} arquivos já processados)"
            else:
                display_text = f"{folder} (sem arquivos .txt)"
            dropdown_folders.options.append(ft.dropdown.Option(key=folder, text=display_text))

        dropdown_folders.value = previous if previous in folders else sorted(folders, reverse=True)[0]

    def handle_stop_ai(e):
        stop_event.set()
        btn_stop_ai.disabled = True
        show_status("Cancelando após o arquivo atual...", "orange")
        _refresh_ui()

    btn_stop_ai.on_click = handle_stop_ai

    def handle_create_redmine_tasks(e):
        selected_tasks = task_list.selected_tasks()
        if not selected_tasks:
            show_status("Selecione ao menos uma tarefa (use Horas a criar ou os checkboxes).", "red")
            _refresh_ui()
            return

        desenvolvedor_id = dropdown_desenvolvedor.value
        if not desenvolvedor_id:
            show_status("Selecione o Desenvolvedor.", "red")
            _refresh_ui()
            return

        btn_create_redmine_tasks.disabled = True
        progress_ring.visible = True
        show_status("Preparando tarefas selecionadas...", "blue")
        _refresh_ui()

        def bg_create():
            bank_path = None
            try:
                remainder = task_list.remainder_tasks()
                results_path = current_analysis_path[0] or dropdown_results.value or ""
                source_diff_folder = current_source_folder[0]

                if remainder:
                    bank_path = save_banco_batch(
                        remainder,
                        user=app_state.get("user") or "",
                        source_analysis=os.path.basename(results_path) if results_path else "",
                        source_diff_folder=source_diff_folder or "",
                        atribuicao_catalogo=dropdown_atribuicao.value or "",
                    )
                    if bank_path:
                        print(f"[BANCO] {len(remainder)} tarefa(s) salvas em {bank_path}")
                        _notify_banco_listeners()

                subtasks_list = [strip_urls_from_description(dict(t)) for t in selected_tasks]

                if source_diff_folder:
                    diff_dir = os.path.join(DIFFS_ROOT, source_diff_folder)
                    if os.path.isdir(diff_dir):
                        subtasks_list, commits_index = prepare_tasks_with_commits(
                            subtasks_list, source_diff_folder
                        )
                    else:
                        commits_index = {}
                else:
                    commits_index = {}

                start_date = date_start.value
                end_date = date_due.value

                show_status(
                    f"Criando Tarefa Pai e {len(subtasks_list)} subtarefa(s). Verifique o console.",
                    "blue",
                )
                _refresh_ui()

                creation_result = create_ai_redmine_tasks(
                    app_state["session"],
                    start_date,
                    end_date,
                    app_state["user"],
                    subtasks_list,
                    sistema=dropdown_sistema.value,
                    orgao_solicitante=dropdown_orgao.value,
                    atribuicao_catalogo=dropdown_atribuicao.value,
                    projeto_vinculado=dropdown_projeto.value,
                    versao=dropdown_versao.value or None,
                    desenvolvedor_id=desenvolvedor_id,
                )

                if not creation_result:
                    if selected_tasks:
                        # Put selected tasks in the bank so nothing is lost after a full failure.
                        save_banco_batch(
                            selected_tasks,
                            user=app_state.get("user") or "",
                            source_analysis=os.path.basename(results_path) if results_path else "",
                            source_diff_folder=source_diff_folder or "",
                            atribuicao_catalogo=dropdown_atribuicao.value or "",
                        )
                        _notify_banco_listeners()
                    show_status("Falha ao criar tarefas no Redmine. Verifique o console.", "red")
                    return

                parent_id = creation_result["parent_id"]
                created_subtasks = creation_result.get("subtasks", [])
                created_ids = {
                    str(item.get("task_id"))
                    for item in created_subtasks
                    if item.get("task_id")
                }
                failed_tasks = [
                    t for t in selected_tasks
                    if str(t.get("task_id") or "") not in created_ids
                ]

                if failed_tasks:
                    save_banco_batch(
                        failed_tasks,
                        user=app_state.get("user") or "",
                        source_analysis=os.path.basename(results_path) if results_path else "",
                        source_diff_folder=source_diff_folder or "",
                        atribuicao_catalogo=dropdown_atribuicao.value or "",
                    )
                    _notify_banco_listeners()
                    print(f"[BANCO] {len(failed_tasks)} subtarefa(s) não criadas devolvidas ao banco.")

                if not created_subtasks:
                    show_status(
                        f"Tarefa pai #{parent_id} criada, mas nenhuma subtarefa foi registrada.",
                        "orange",
                    )
                    return

                created_task_objs = [
                    t for t in subtasks_list
                    if str(t.get("task_id") or "") in created_ids
                ] or subtasks_list[:len(created_subtasks)]

                fechamento_payload = build_fechamento_payload(
                    parent_id=parent_id,
                    id_items=[
                        {
                            "id": created["id"],
                            "title": created.get("title") or subtask.get("task_title") or "",
                            "files": [],
                        }
                        for created, subtask in zip(created_subtasks, created_task_objs)
                    ],
                    tasks=created_task_objs,
                    commits_index=commits_index,
                    generated_by=app_state["user"] or "",
                    source_analysis=os.path.basename(results_path) if results_path else "",
                    source_diff_folder=source_diff_folder or "",
                    preserve_files=False,
                )

                fechamento_dir = None
                if source_diff_folder:
                    candidate = os.path.join(DIFFS_ROOT, source_diff_folder)
                    if os.path.isdir(candidate):
                        fechamento_dir = candidate

                fechamento_path = save_fechamento(
                    fechamento_payload,
                    app_state["user"] or "",
                    output_dir=fechamento_dir,
                )

                for listener in fechamento_listeners or []:
                    try:
                        listener(fechamento_path)
                    except Exception as listener_ex:
                        print(f"[FECHAMENTO] Listener falhou: {listener_ex}")

                leftover_note = ""
                if remainder or failed_tasks:
                    leftover_note = (
                        f" {len(remainder) + len(failed_tasks)} tarefa(s) ficaram no banco de horas."
                    )

                show_status(
                    f"Concluído! Pai #{parent_id}, {len(created_subtasks)} subtarefa(s). "
                    f"Fechamento: {fechamento_path}.{leftover_note}",
                    "green",
                )

                # Refresh list: remove created tasks from the on-screen selection source.
                remaining_on_screen = [
                    t for t in task_list.tasks
                    if str(t.get("task_id") or "") not in created_ids
                ]
                task_list.set_tasks(remaining_on_screen)
                btn_create_redmine_tasks.visible = bool(remaining_on_screen)

            except json.JSONDecodeError:
                show_status("Falha ao decodificar a resposta. Formato JSON inválido.", "red")
            except Exception as ex:
                show_status(f"Falha ao gerar tarefas: {str(ex)}", "red")
            finally:
                btn_create_redmine_tasks.disabled = False
                progress_ring.visible = False
                _refresh_ui()

        Thread(target=bg_create, daemon=True).start()

    btn_create_redmine_tasks.on_click = handle_create_redmine_tasks

    def handle_process_ai(e):
        selected_model = dropdown_model.value
        folder_name = dropdown_folders.value
        atribuicao = dropdown_atribuicao.value

        if not selected_model:
            show_status("Selecione um Modelo de IA.", "red")
            _refresh_ui()
            return
        if not folder_name:
            show_status("Selecione uma pasta de diffs.", "red")
            _refresh_ui()
            return
        if not atribuicao:
            show_status("Selecione a Atribuição Catálogo - Desenv.", "red")
            _refresh_ui()
            return

        stop_event.clear()
        btn_process_ai.disabled = True
        btn_stop_ai.disabled = False
        btn_stop_ai.visible = True
        progress_ring.visible = True
        show_status(f"Iniciando processamento por arquivo ({selected_model})...", "purple")
        _refresh_ui()

        def prepare_directory_for_new_run(folder_path: str):
            # The checkpoint is kept on purpose so an interrupted run can resume.
            files_to_remove = [
                "batch_info.json",
                "ai_tasks_result.jsonl",
                "ai_tasks_result.json",
            ]
            for filename in files_to_remove:
                file_path = os.path.join(folder_path, filename)
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"[CLEANUP] Arquivo antigo removido: {filename}")

        def bg_ai_process():
            try:
                target_dir = os.path.join(DIFFS_ROOT, folder_name)
                prepare_directory_for_new_run(target_dir)

                diff_items = _collect_diff_items(target_dir)

                if not diff_items:
                    show_status(f"Nenhum conteúdo válido de diff encontrado em {folder_name}", "red")
                    return

                done_labels = _checkpoint_done_labels(target_dir)
                already = sum(1 for label, _content in diff_items if label in done_labels)
                pending = len(diff_items) - already
                show_status(
                    f"Pasta {folder_name}: {already} de {len(diff_items)} arquivo(s) já processados. "
                    f"{pending} pendente(s).",
                    "purple",
                )
                _refresh_ui()

                def on_progress(step, total, message):
                    show_status(f"[{step}/{total}] {message}", "purple")
                    _refresh_ui()

                final_payload = analyze_diffs_grouped_with_claude(
                    diff_items,
                    selected_model,
                    on_progress=on_progress,
                    output_dir=target_dir,
                    should_cancel=stop_event.is_set,
                    atribuicao_catalogo=atribuicao,
                    min_hours=get_min_task_hours(),
                )

                final_payload["source_diff_folder"] = folder_name
                final_payload["generated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
                final_payload["generated_by"] = app_state["user"] or ""
                final_payload["model"] = selected_model
                final_payload["atribuicao_catalogo"] = atribuicao

                results_file = save_results(final_payload, app_state["user"] or "")
                refresh_saved_results(select_path=results_file)
                _show_tasks_from_payload(final_payload, results_file)

                task_count = len(final_payload.get("tasks", []))
                total_h = sum_task_hours(final_payload.get("tasks", []))
                if final_payload.get("partial"):
                    show_status(
                        f"Processamento interrompido. {task_count} tarefa(s) ({total_h:g}h) "
                        f"parciais salvas em: {results_file}",
                        "orange",
                    )
                else:
                    show_status(
                        f"Processamento concluído! {task_count} tarefa(s) ({total_h:g}h) "
                        f"salvas em: {results_file}",
                        "green",
                    )

            except Exception as ex:
                show_status(f"Erro no processamento com IA: {str(ex)}", "red")
            finally:
                btn_process_ai.disabled = False
                btn_stop_ai.visible = False
                btn_stop_ai.disabled = False
                progress_ring.visible = False
                _refresh_ui()

        Thread(target=bg_ai_process, daemon=True).start()

    btn_process_ai.on_click = handle_process_ai

    def sync_ui():
        refresh_ai_folders()
        refresh_saved_results(select_path=dropdown_results.value)
        if app_state["session"]:
            lbl_logged_in.value = app_state["user"]
            _apply_field_defaults()
            Thread(target=_load_open_versions, daemon=True).start()
        else:
            lbl_status.visible = False
            dropdown_versao.options = []
            dropdown_versao.value = None
            dropdown_versao.hint_text = "Faça login para carregar as versões abertas"
            _apply_field_defaults()

    sync_callbacks.append(sync_ui)

    def on_diffs_changed():
        refresh_ai_folders()
        _refresh_ui()

    if diffs_listeners is not None:
        diffs_listeners.append(on_diffs_changed)

    def on_folder_refresh():
        refresh_ai_folders()
        _refresh_ui()

    if folder_refresh_listeners is not None:
        folder_refresh_listeners.append(on_folder_refresh)

    sync_ui()

    return ft.Tab(
        text="Análise com IA",
        icon=ft.Icons.AUTO_AWESOME,
        content=ft.Container(content=ai_view, padding=20, expand=True),
    )

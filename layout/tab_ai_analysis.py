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
    synthesize_tasks_for_redmine,
)
from diff_task_automation import create_ai_redmine_tasks
from redmine_mappings import (
    SYSTEM_OPTIONS,
    ORGAN_OPTIONS,
    PROJECT_FILTER_OPTIONS,
    ROLE_OPTIONS,
    USER_OPTIONS,
)
from utils.ai_tasks_store import list_saved_results, load_tasks, save_results, save_fechamento
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
):
    lbl_logged_in = ft.Text("", color="green", weight=ft.FontWeight.BOLD, size=14)
    lbl_status = ft.Text("", visible=False, weight=ft.FontWeight.BOLD)
    progress_ring = ft.ProgressRing(visible=False, width=20, height=20)

    stop_event = Event()

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

    txt_ai_hours = ft.TextField(
        label="Total de Horas",
        width=150,
        input_filter=ft.InputFilter(allow=True, regex_string=r"^[0-9.]*$", replacement_string=""),
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
        if date_start.page:
            date_start.update()
            date_due.update()

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
        "Atribuição Catálogo", ROLE_OPTIONS, defaults["atribuicao"]
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

    wrapper_ai_box = ft.Container(
        content=ft.Column([
            ft.Text("Análise Inteligente e Geração de Tarefas", weight=ft.FontWeight.BOLD, size=15, color="purple"),
            ft.Row([dropdown_model, dropdown_folders, txt_ai_hours], alignment=ft.MainAxisAlignment.START, wrap=True),
            ft.Row([btn_process_ai, btn_stop_ai], alignment=ft.MainAxisAlignment.START, wrap=True),
            ft.Divider(),
            ft.Row([dropdown_results, btn_create_redmine_tasks], alignment=ft.MainAxisAlignment.START, wrap=True),
            ft.Text("Campos Redmine (tarefa pai e subtarefas)", weight=ft.FontWeight.BOLD, size=13),
            ft.Row([dropdown_month], alignment=ft.MainAxisAlignment.START),
            ft.Row([date_start, date_due], alignment=ft.MainAxisAlignment.START, spacing=20, tight=True),
            ft.Row([dropdown_versao], alignment=ft.MainAxisAlignment.START),
            ft.Row([dropdown_sistema, dropdown_orgao], alignment=ft.MainAxisAlignment.START, wrap=True),
            ft.Row([dropdown_atribuicao, dropdown_projeto], alignment=ft.MainAxisAlignment.START, wrap=True),
            ft.Row([dropdown_desenvolvedor], alignment=ft.MainAxisAlignment.START, wrap=True),
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
        page = ai_view.page
        if page:
            page.update()

    def show_status(text: str, color: str):
        lbl_status.value = text
        lbl_status.color = color
        lbl_status.visible = True

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
        else:
            dropdown_results.value = None

        btn_create_redmine_tasks.visible = bool(entries)

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
        results_path = dropdown_results.value
        if not results_path:
            show_status("Selecione uma análise salva.", "red")
            _refresh_ui()
            return

        desenvolvedor_id = dropdown_desenvolvedor.value
        if not desenvolvedor_id:
            show_status("Selecione o Desenvolvedor.", "red")
            _refresh_ui()
            return

        btn_create_redmine_tasks.disabled = True
        progress_ring.visible = True
        show_status("Lendo respostas da IA e formatando tarefas...", "blue")
        _refresh_ui()

        def bg_create():
            try:
                with open(results_path, "r", encoding="utf-8") as f:
                    analysis_payload = json.load(f)

                subtasks_list = analysis_payload.get("tasks", []) if isinstance(analysis_payload, dict) else []
                if not subtasks_list:
                    subtasks_list = load_tasks(results_path)

                if not subtasks_list:
                    show_status("Nenhuma tarefa pôde ser extraída do arquivo de resultados.", "red")
                    return

                selected_model = (
                    (analysis_payload.get("model") if isinstance(analysis_payload, dict) else None)
                    or dropdown_model.value
                    or list(MODEL_CONFIGS.keys())[0]
                )

                source_diff_folder = (
                    analysis_payload.get("source_diff_folder")
                    if isinstance(analysis_payload, dict) else None
                )
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

                original_count = len(subtasks_list)
                min_hours = get_min_task_hours()
                show_status(
                    f"Sintetizando {original_count} tarefa(s) (mínimo {min_hours}h cada)...",
                    "blue",
                )
                _refresh_ui()

                subtasks_list = synthesize_tasks_for_redmine(
                    subtasks_list,
                    selected_model,
                    min_hours=min_hours,
                )

                subtasks_list = [strip_urls_from_description(task) for task in subtasks_list]

                start_date = date_start.value
                end_date = date_due.value

                show_status(
                    f"Criando Tarefa Pai e {len(subtasks_list)} subtarefa(s) "
                    f"(de {original_count} originais). Verifique o console.",
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
                    show_status("Falha ao criar tarefas no Redmine. Verifique o console.", "red")
                    return

                parent_id = creation_result["parent_id"]
                created_subtasks = creation_result.get("subtasks", [])

                if not created_subtasks:
                    show_status(
                        f"Tarefa pai #{parent_id} criada, mas nenhuma subtarefa foi registrada.",
                        "orange",
                    )
                    return

                fechamento_payload = build_fechamento_payload(
                    parent_id=parent_id,
                    id_items=[
                        {
                            "id": created["id"],
                            "title": created.get("title") or subtask.get("task_title") or "",
                            "files": [],
                        }
                        for created, subtask in zip(created_subtasks, subtasks_list)
                    ],
                    tasks=subtasks_list,
                    commits_index=commits_index,
                    generated_by=app_state["user"] or "",
                    source_analysis=os.path.basename(results_path),
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

                show_status(
                    f"Concluído! Pai #{parent_id}, {len(created_subtasks)} subtarefa(s). "
                    f"Fechamento salvo em: {fechamento_path}",
                    "green",
                )

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
        hours_str = (txt_ai_hours.value or "").strip()

        if not selected_model:
            show_status("Selecione um Modelo de IA.", "red")
            _refresh_ui()
            return
        if not folder_name:
            show_status("Selecione uma pasta de diffs.", "red")
            _refresh_ui()
            return
        if not hours_str:
            show_status("Insira o total de horas.", "red")
            _refresh_ui()
            return

        try:
            total_hours = float(hours_str)
        except ValueError:
            show_status("Valor de horas inválido.", "red")
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
                    total_hours,
                    selected_model,
                    on_progress=on_progress,
                    output_dir=target_dir,
                    should_cancel=stop_event.is_set,
                )

                final_payload["source_diff_folder"] = folder_name
                final_payload["generated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
                final_payload["generated_by"] = app_state["user"] or ""
                final_payload["model"] = selected_model

                results_file = save_results(final_payload, app_state["user"] or "")
                refresh_saved_results(select_path=results_file)

                task_count = len(final_payload.get("tasks", []))
                if final_payload.get("partial"):
                    show_status(
                        f"Processamento interrompido. {task_count} tarefa(s) parciais salvas em: {results_file}",
                        "orange",
                    )
                else:
                    show_status(
                        f"Processamento concluído! {task_count} tarefa(s) salvas em: {results_file}",
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
            txt_ai_hours.value = ""
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

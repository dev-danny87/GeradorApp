# tab_close_tasks.py
import flet as ft
import json
import os
from threading import Thread

from task_automation import get_redmine_subtasks, close_single_subtask
from services.ai_api_request import MODEL_CONFIGS, synthesize_tasks_for_redmine
from utils.ai_tasks_store import list_saved_fechamentos, list_saved_results, load_fechamento
from utils.fechamento_builder import (
    SOURCE_ANALYSIS,
    SOURCE_CHECKPOINT,
    list_diff_folders_with_checkpoint,
    regenerate_fechamento,
    resolve_analysis_path,
)


def _parse_close_json(json_text: str) -> list:
    parsed = json.loads(json_text)

    if isinstance(parsed, dict):
        tasks = parsed.get("tasks")
        if not isinstance(tasks, list):
            raise ValueError("O JSON deve conter a lista 'tasks'.")
        items = tasks
    elif isinstance(parsed, list):
        items = parsed
    else:
        raise ValueError("O JSON deve ser um objeto com 'tasks' ou uma lista.")

    normalized = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Item {index}: esperado um objeto JSON.")
        raw_id = item.get("id")
        if raw_id is None or str(raw_id).strip() == "":
            raise ValueError(f"Item {index}: informe o 'id' da subtarefa.")
        files = item.get("files") or []
        if not isinstance(files, list):
            raise ValueError(f"Item {index}: 'files' deve ser uma lista de caminhos.")
        normalized.append({
            "id": str(raw_id).strip(),
            "notas": str(item.get("notas") or ""),
            "files": [str(path).strip() for path in files if str(path).strip()],
        })
    return normalized


def create_close_tasks_tab(page: ft.Page, app_state, set_auth, sync_callbacks, fechamento_listeners=None):
    selected_files = []
    cached_subtasks: list[dict] = []

    # ==========================================
    # FILE PICKER & VISUAL LIST
    # ==========================================
    files_list_view = ft.Column(spacing=5, width=500, scroll=ft.ScrollMode.AUTO, height=120)

    def update_file_list_ui():
        files_list_view.controls.clear()
        if not selected_files:
            files_list_view.controls.append(
                ft.Text("Nenhum arquivo selecionado.", color="grey", italic=True, text_align=ft.TextAlign.CENTER)
            )
        else:
            for file_info in selected_files:
                row = ft.Row([
                    ft.Icon(ft.Icons.INSERT_DRIVE_FILE, color="blue", size=20),
                    ft.Text(file_info["name"], expand=True, size=13, tooltip=file_info["name"]),
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE,
                        icon_color="red",
                        tooltip="Remover arquivo",
                        on_click=lambda e, f=file_info: remove_file(f)
                    )
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                files_list_view.controls.append(row)

        if page:
            page.update()

    def remove_file(file_to_remove):
        if file_to_remove in selected_files:
            selected_files.remove(file_to_remove)
        update_file_list_ui()

    def on_files_selected(e: ft.FilePickerResultEvent):
        if e.files:
            for f in e.files:
                if not any(existing["path"] == f.path for existing in selected_files):
                    selected_files.append({"name": f.name, "path": f.path})
        update_file_list_ui()

    file_picker = ft.FilePicker(on_result=on_files_selected)
    page.overlay.append(file_picker)
    update_file_list_ui()

    # ==========================================
    # VIEW: TASK CLOSING
    # ==========================================
    lbl_logged_in = ft.Text("", color="green", weight=ft.FontWeight.BOLD, size=14)
    lbl_form_error = ft.Text("", visible=False, weight=ft.FontWeight.BOLD)

    txt_parent_id = ft.TextField(
        label="ID da Sprint (Pai)",
        width=200,
        hint_text="Ex: 33110",
        icon=ft.Icons.ACCOUNT_TREE,
    )
    btn_search = ft.ElevatedButton("Buscar Subtarefas", icon=ft.Icons.SEARCH)
    search_progress = ft.ProgressRing(visible=False, width=20, height=20)

    dropdown_subtasks = ft.Dropdown(
        label="Selecione a Subtarefa para Fechar",
        width=600,
        visible=False,
    )

    btn_copy_ids = ft.ElevatedButton(
        "Copiar IDs",
        icon=ft.Icons.CONTENT_COPY,
        visible=False,
        tooltip="Copia id - título de todas as subtarefas buscadas",
    )
    btn_fill_json_template = ft.ElevatedButton(
        "Gerar JSON",
        icon=ft.Icons.DATA_OBJECT,
        visible=False,
        tooltip="Preenche o JSON com os IDs buscados (notas e files vazios)",
    )

    btn_pick_file = ft.ElevatedButton(
        "Adicionar Evidências",
        icon=ft.Icons.ADD_PHOTO_ALTERNATE,
        on_click=lambda _: file_picker.pick_files(allow_multiple=True),
    )
    btn_close_task = ft.ElevatedButton(
        "Finalizar Subtarefa Escolhida",
        icon=ft.Icons.DONE,
        color="white",
        bgcolor="green",
        visible=False,
    )

    txt_notas = ft.TextField(
        label="Notas",
        multiline=True,
        min_lines=3,
        max_lines=5,
        width=600,
        icon=ft.Icons.NOTE,
        visible=False,
    )

    txt_close_json = ft.TextField(
        label="JSON para Fechar em Lote",
        hint_text='{"tasks":[{"id":"33111","notas":"...","files":["C:\\\\caminho\\\\evidencia.png"]}]}',
        multiline=True,
        min_lines=8,
        max_lines=12,
        icon=ft.Icons.DATA_OBJECT,
    )
    json_container = ft.Container(content=txt_close_json, width=600, height=220)

    dropdown_fechamento = ft.Dropdown(
        label="Arquivo de Fechamento",
        width=600,
        hint_text="Selecione um fechamento salvo em ./diffs (ou ./ai_tasks legado)",
    )

    dropdown_analysis = ft.Dropdown(
        label="Análise IA (base para regenerar notas)",
        width=600,
        hint_text="Selecione a análise salva em ./ai_tasks",
    )

    dropdown_checkpoint_folder = ft.Dropdown(
        label="Pasta de Diffs (checkpoint)",
        width=600,
        hint_text="Pastas em ./diffs com ai_tasks_checkpoint.json",
        visible=False,
    )

    radio_source = ft.RadioGroup(
        content=ft.Row(
            [
                ft.Radio(value=SOURCE_ANALYSIS, label="Análise salva"),
                ft.Radio(value=SOURCE_CHECKPOINT, label="Checkpoint da pasta de diffs"),
            ],
            wrap=True,
        ),
        value=SOURCE_ANALYSIS,
    )

    chk_tasks_only = ft.Checkbox(
        label="Usar somente tarefas (ignorar re-leitura de diffs)",
        value=False,
        tooltip=(
            "Monta as notas só com título/descrição/arquivos/commit_links já presentes "
            "na análise ou no checkpoint, sem reprocessar os .txt de diffs."
        ),
    )

    btn_regenerate_fechamento = ft.ElevatedButton(
        "Regenerar Fechamento",
        icon=ft.Icons.AUTORENEW,
        color="white",
        bgcolor="purple",
        tooltip=(
            "Gera notas detalhadas com commits a partir da análise/checkpoint, "
            "usando os IDs do fechamento selecionado (ou das subtarefas buscadas)"
        ),
    )

    btn_close_json = ft.ElevatedButton(
        "Fechar via JSON",
        icon=ft.Icons.PLAYLIST_ADD_CHECK,
        color="white",
        bgcolor="green",
        tooltip="Fecha cada subtarefa do JSON com suas notas e arquivos",
    )

    lote_section = ft.Column(
        [
            ft.Text(
                "Fechar em lote via arquivo de fechamento ou JSON manual:",
                weight=ft.FontWeight.BOLD,
            ),
            dropdown_fechamento,
            ft.Text("Fonte das notas:", weight=ft.FontWeight.W_500),
            radio_source,
            dropdown_analysis,
            dropdown_checkpoint_folder,
            chk_tasks_only,
            ft.Row(
                [btn_regenerate_fechamento],
                alignment=ft.MainAxisAlignment.START,
                width=600,
            ),
            json_container,
            ft.Row([btn_close_json], alignment=ft.MainAxisAlignment.END, width=600),
        ],
        spacing=10,
        visible=False,
    )

    user_header = ft.Row([
        ft.Icon(ft.Icons.PERSON, color="green", size=20),
        lbl_logged_in,
        ft.IconButton(
            icon=ft.Icons.LOGOUT,
            icon_color="red",
            icon_size=20,
            tooltip="Sair da conta",
            on_click=lambda e: set_auth(None, None),
        ),
    ], alignment=ft.MainAxisAlignment.END)

    upload_container = ft.Container(
        content=ft.Column([
            btn_pick_file,
            ft.Divider(height=10, color="transparent"),
            files_list_view,
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        padding=20,
        border=ft.border.all(1, ft.Colors.OUTLINE),
        border_radius=10,
        visible=False,
        width=600,
    )

    task_view = ft.Column(
        [
            user_header,
            ft.Text(
                "1. Digite a Sprint Pai e busque subtarefas para fechar uma a uma, "
                "ou use o arquivo de fechamento abaixo para lote.",
                weight=ft.FontWeight.BOLD,
            ),
            ft.Row([txt_parent_id, btn_search, search_progress], alignment=ft.MainAxisAlignment.CENTER),
            ft.Divider(height=15, color="transparent"),
            ft.Row(
                [btn_copy_ids, btn_fill_json_template],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=10,
                wrap=True,
            ),
            dropdown_subtasks,
            upload_container,
            txt_notas,
            ft.Row([btn_close_task], alignment=ft.MainAxisAlignment.END, width=600),
            ft.Divider(height=20),
            lote_section,
            lbl_form_error,
        ],
        alignment=ft.MainAxisAlignment.START,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=15,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )

    def _show_status(message: str, color: str = "red"):
        lbl_form_error.value = message
        lbl_form_error.color = color
        lbl_form_error.visible = True
        page.update()

    def _set_single_close_ui_visible(visible: bool):
        dropdown_subtasks.visible = visible
        upload_container.visible = visible
        txt_notas.visible = visible
        btn_close_task.visible = visible
        btn_copy_ids.visible = visible
        btn_fill_json_template.visible = visible

    def _set_lote_ui_visible(visible: bool):
        lote_section.visible = visible

    def refresh_fechamento_dropdown(select_path: str | None = None):
        entries = list_saved_fechamentos()
        dropdown_fechamento.options.clear()
        for entry in entries:
            dropdown_fechamento.options.append(
                ft.dropdown.Option(key=entry["path"], text=entry["label"])
            )

        if entries:
            if select_path and any(entry["path"] == select_path for entry in entries):
                dropdown_fechamento.value = select_path
            elif dropdown_fechamento.value not in [entry["path"] for entry in entries]:
                dropdown_fechamento.value = entries[0]["path"]
        else:
            dropdown_fechamento.value = None

    def refresh_analysis_dropdown(select_path: str | None = None):
        entries = list_saved_results()
        dropdown_analysis.options.clear()
        for entry in entries:
            dropdown_analysis.options.append(
                ft.dropdown.Option(key=entry["path"], text=entry["label"])
            )

        if entries:
            if select_path and any(entry["path"] == select_path for entry in entries):
                dropdown_analysis.value = select_path
            elif dropdown_analysis.value not in [entry["path"] for entry in entries]:
                dropdown_analysis.value = entries[0]["path"]
        else:
            dropdown_analysis.value = None

    def refresh_checkpoint_dropdown(select_folder: str | None = None):
        entries = list_diff_folders_with_checkpoint()
        dropdown_checkpoint_folder.options.clear()
        for entry in entries:
            dropdown_checkpoint_folder.options.append(
                ft.dropdown.Option(key=entry["folder"], text=entry["label"])
            )

        if entries:
            if select_folder and any(entry["folder"] == select_folder for entry in entries):
                dropdown_checkpoint_folder.value = select_folder
            elif dropdown_checkpoint_folder.value not in [entry["folder"] for entry in entries]:
                dropdown_checkpoint_folder.value = entries[0]["folder"]
        else:
            dropdown_checkpoint_folder.value = None

    def sync_source_controls():
        use_checkpoint = (radio_source.value or SOURCE_ANALYSIS) == SOURCE_CHECKPOINT
        dropdown_analysis.visible = not use_checkpoint
        dropdown_checkpoint_folder.visible = use_checkpoint

    def on_fechamento_saved(select_path: str | None = None):
        if not app_state.get("session"):
            return
        refresh_fechamento_dropdown(select_path=select_path)
        refresh_analysis_dropdown(select_path=dropdown_analysis.value)
        refresh_checkpoint_dropdown(select_folder=dropdown_checkpoint_folder.value)
        sync_source_controls()
        _set_lote_ui_visible(True)
        if dropdown_fechamento.value:
            try:
                payload = load_fechamento(dropdown_fechamento.value)
                txt_close_json.value = json.dumps(payload, ensure_ascii=False, indent=2)
                parent_id = payload.get("parent_id")
                if parent_id and not (txt_parent_id.value or "").strip():
                    txt_parent_id.value = str(parent_id)
                source_analysis = payload.get("source_analysis")
                resolved = resolve_analysis_path(source_analysis)
                if resolved:
                    refresh_analysis_dropdown(select_path=resolved)
                source_diff = payload.get("source_diff_folder")
                if source_diff:
                    refresh_checkpoint_dropdown(select_folder=source_diff)
            except Exception:
                pass
        if page:
            page.update()

    if fechamento_listeners is not None:
        fechamento_listeners.append(on_fechamento_saved)

    # ==========================================
    # LOGIC
    # ==========================================
    def sync_ui():
        if app_state["session"]:
            lbl_logged_in.value = app_state["user"]
            refresh_fechamento_dropdown(select_path=dropdown_fechamento.value)
            refresh_analysis_dropdown(select_path=dropdown_analysis.value)
            refresh_checkpoint_dropdown(select_folder=dropdown_checkpoint_folder.value)
            sync_source_controls()
            _set_lote_ui_visible(True)
            if dropdown_fechamento.value:
                try:
                    payload = load_fechamento(dropdown_fechamento.value)
                    txt_close_json.value = json.dumps(payload, ensure_ascii=False, indent=2)
                    parent_id = payload.get("parent_id")
                    if parent_id and not txt_parent_id.value.strip():
                        txt_parent_id.value = str(parent_id)
                    resolved = resolve_analysis_path(payload.get("source_analysis"))
                    if resolved:
                        refresh_analysis_dropdown(select_path=resolved)
                    source_diff = payload.get("source_diff_folder")
                    if source_diff:
                        refresh_checkpoint_dropdown(select_folder=source_diff)
                except Exception:
                    pass
        else:
            txt_parent_id.value = ""
            txt_notas.value = ""
            txt_close_json.value = ""
            dropdown_subtasks.options = []
            dropdown_subtasks.value = None
            dropdown_fechamento.options = []
            dropdown_fechamento.value = None
            dropdown_analysis.options = []
            dropdown_analysis.value = None
            dropdown_checkpoint_folder.options = []
            dropdown_checkpoint_folder.value = None
            radio_source.value = SOURCE_ANALYSIS
            chk_tasks_only.value = False
            cached_subtasks.clear()
            _set_single_close_ui_visible(False)
            _set_lote_ui_visible(False)
            lbl_form_error.visible = False
            selected_files.clear()
            update_file_list_ui()
            sync_source_controls()

    sync_callbacks.append(sync_ui)

    def handle_search(e):
        parent_id = txt_parent_id.value.strip()
        if not parent_id:
            return

        btn_search.disabled = True
        search_progress.visible = True
        page.update()

        def bg_search():
            subs = get_redmine_subtasks(app_state["session"], parent_id)
            cached_subtasks.clear()
            if subs:
                cached_subtasks.extend(subs)
                dropdown_subtasks.options = [
                    ft.dropdown.Option(key=s["id"], text=f"{s['id']} - {s['title']}") for s in subs
                ]
                dropdown_subtasks.value = None
                _set_single_close_ui_visible(True)
                lbl_form_error.visible = False
            else:
                _set_single_close_ui_visible(False)
                _show_status("Nenhuma subtarefa encontrada.", "red")

            btn_search.disabled = False
            search_progress.visible = False
            page.update()

        Thread(target=bg_search, daemon=True).start()

    def handle_copy_ids(e):
        if not cached_subtasks:
            _show_status("Busque as subtarefas antes de copiar.", "red")
            return
        text = "\n".join(f"{s['id']} - {s['title']}" for s in cached_subtasks)
        page.set_clipboard(text)
        _show_status(f"{len(cached_subtasks)} subtarefa(s) copiada(s) para a área de transferência.", "green")

    def handle_fill_json_template(e):
        if not cached_subtasks:
            _show_status("Busque as subtarefas antes de gerar o JSON.", "red")
            return
        payload = {
            "tasks": [
                {"id": s["id"], "notas": "", "files": []}
                for s in cached_subtasks
            ]
        }
        txt_close_json.value = json.dumps(payload, ensure_ascii=False, indent=2)
        _show_status("JSON gerado. Preencha notas e caminhos dos arquivos.", "green")

    def handle_fechamento_selected(e):
        fechamento_path = dropdown_fechamento.value
        if not fechamento_path:
            return
        try:
            payload = load_fechamento(fechamento_path)
            txt_close_json.value = json.dumps(payload, ensure_ascii=False, indent=2)
            parent_id = payload.get("parent_id")
            if parent_id and not txt_parent_id.value.strip():
                txt_parent_id.value = str(parent_id)
            resolved = resolve_analysis_path(payload.get("source_analysis"))
            if resolved:
                refresh_analysis_dropdown(select_path=resolved)
            _show_status(
                f"Fechamento carregado: {len(payload.get('tasks', []))} subtarefa(s).",
                "green",
            )
        except Exception as err:
            _show_status(f"Falha ao carregar fechamento: {err}", "red")

    def handle_regenerate_fechamento(e):
        source_mode = radio_source.value or SOURCE_ANALYSIS
        analysis_path = dropdown_analysis.value
        checkpoint_folder = dropdown_checkpoint_folder.value
        use_diffs = not bool(chk_tasks_only.value)

        if source_mode == SOURCE_CHECKPOINT:
            if not checkpoint_folder:
                _show_status(
                    "Selecione a pasta de diffs que contém ai_tasks_checkpoint.json.",
                    "red",
                )
                return
        elif not analysis_path:
            _show_status("Selecione uma análise IA para regenerar o fechamento.", "red")
            return

        id_items: list[dict] = []
        parent_id = (txt_parent_id.value or "").strip()
        source_diff_folder = checkpoint_folder if source_mode == SOURCE_CHECKPOINT else None
        preserve_files = True

        fechamento_path = dropdown_fechamento.value
        if fechamento_path:
            try:
                base = load_fechamento(fechamento_path)
            except Exception as err:
                _show_status(f"Falha ao ler fechamento base: {err}", "red")
                return
            parent_id = parent_id or str(base.get("parent_id") or "")
            if source_mode != SOURCE_CHECKPOINT:
                source_diff_folder = base.get("source_diff_folder") or None
            elif not source_diff_folder:
                source_diff_folder = base.get("source_diff_folder") or checkpoint_folder
            id_items = [
                {
                    "id": str(item.get("id", "")).strip(),
                    "title": "",
                    "files": item.get("files") or [],
                }
                for item in (base.get("tasks") or [])
                if str(item.get("id", "")).strip()
            ]
            if cached_subtasks:
                title_by_id = {s["id"]: s.get("title", "") for s in cached_subtasks}
                for item in id_items:
                    item["title"] = title_by_id.get(item["id"], "")
        elif cached_subtasks:
            id_items = [
                {"id": s["id"], "title": s.get("title", ""), "files": []}
                for s in cached_subtasks
            ]
            preserve_files = False
        else:
            _show_status(
                "Selecione um fechamento existente ou busque as subtarefas do pai.",
                "red",
            )
            return

        if not parent_id:
            _show_status("Informe o ID da tarefa pai.", "red")
            return
        if not id_items:
            _show_status("Nenhum ID de subtarefa disponível para regenerar.", "red")
            return

        btn_regenerate_fechamento.disabled = True
        mode_label = "checkpoint" if source_mode == SOURCE_CHECKPOINT else "análise"
        diffs_label = "com diffs" if use_diffs else "somente tarefas"
        _show_status(
            f"Regenerando fechamento ({mode_label}, {diffs_label})...",
            "blue",
        )

        def bg_regenerate():
            try:
                payload, saved_path = regenerate_fechamento(
                    analysis_path=analysis_path if source_mode == SOURCE_ANALYSIS else None,
                    id_items=id_items,
                    parent_id=parent_id,
                    user=app_state.get("user") or "",
                    diff_folder=source_diff_folder,
                    source_mode=source_mode,
                    use_diffs=use_diffs,
                    preserve_files=preserve_files,
                    synthesize_fn=synthesize_tasks_for_redmine,
                    selected_model=list(MODEL_CONFIGS.keys())[0],
                    target_task_count=len(id_items),
                )
                txt_close_json.value = json.dumps(payload, ensure_ascii=False, indent=2)
                if not (txt_parent_id.value or "").strip():
                    txt_parent_id.value = str(parent_id)
                for listener in fechamento_listeners or []:
                    try:
                        listener(saved_path)
                    except Exception as listener_ex:
                        print(f"[FECHAMENTO] Listener falhou: {listener_ex}")
                refresh_fechamento_dropdown(select_path=saved_path)
                _show_status(
                    f"Fechamento regenerado ({len(payload.get('tasks', []))} tarefa(s)): {saved_path}",
                    "green",
                )
            except Exception as ex:
                _show_status(f"Falha ao regenerar fechamento: {ex}", "red")
            finally:
                btn_regenerate_fechamento.disabled = False
                page.update()

        Thread(target=bg_regenerate, daemon=True).start()

    def handle_source_change(e):
        sync_source_controls()
        page.update()

    def handle_close(e):
        sub_id = dropdown_subtasks.value
        if not sub_id:
            _show_status("Selecione uma subtarefa na lista.", "red")
            return

        lbl_form_error.visible = False
        page.update()

        files_to_upload = list(selected_files)
        selected_files.clear()
        update_file_list_ui()

        Thread(
            target=close_single_subtask,
            kwargs={
                "session": app_state["session"],
                "sub_id": sub_id,
                "files_list": files_to_upload,
                "notas": txt_notas.value or "",
            },
            daemon=True,
        ).start()

    def handle_close_json(e):
        json_text = (txt_close_json.value or "").strip()
        if not json_text:
            _show_status("Informe o JSON de subtarefas para fechar.", "red")
            return

        try:
            items = _parse_close_json(json_text)
        except Exception as err:
            _show_status(f"Erro no formato JSON: {err}", "red")
            return

        if not items:
            _show_status("O JSON não contém subtarefas.", "red")
            return

        lbl_form_error.visible = False
        btn_close_json.disabled = True
        page.update()

        def bg_close_batch():
            try:
                for index, item in enumerate(items, start=1):
                    files_list = []
                    for path in item["files"]:
                        if not os.path.isfile(path):
                            print(f"[FECHAR JSON] Arquivo inexistente (ignorado): {path}")
                            continue
                        files_list.append({"name": os.path.basename(path), "path": path})

                    print(
                        f"[FECHAR JSON] ({index}/{len(items)}) Fechando subtarefa #{item['id']} "
                        f"com {len(files_list)} arquivo(s)..."
                    )
                    close_single_subtask(
                        session=app_state["session"],
                        sub_id=item["id"],
                        files_list=files_list,
                        notas=item["notas"],
                    )

                _show_status(
                    f"Lote concluído: {len(items)} subtarefa(s) processada(s). Verifique o console.",
                    "green",
                )
            except Exception as ex:
                _show_status(f"Falha no lote JSON: {ex}", "red")
            finally:
                btn_close_json.disabled = False
                page.update()

        Thread(target=bg_close_batch, daemon=True).start()

    btn_search.on_click = handle_search
    btn_copy_ids.on_click = handle_copy_ids
    btn_fill_json_template.on_click = handle_fill_json_template
    btn_close_task.on_click = handle_close
    btn_close_json.on_click = handle_close_json
    btn_regenerate_fechamento.on_click = handle_regenerate_fechamento
    dropdown_fechamento.on_change = handle_fechamento_selected
    radio_source.on_change = handle_source_change

    sync_ui()

    return ft.Tab(
        text="Fechar Tarefas",
        icon=ft.Icons.CHECKLIST,
        content=ft.Container(content=task_view, padding=20, expand=True),
    )

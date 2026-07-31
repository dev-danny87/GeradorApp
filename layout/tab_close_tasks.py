# tab_close_tasks.py
import flet as ft
import json
import os
from threading import Thread

from task_automation import get_redmine_subtasks, close_single_subtask


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


def create_close_tasks_tab(page: ft.Page, app_state, set_auth, sync_callbacks):
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
    json_container = ft.Container(content=txt_close_json, width=600, height=220, visible=False)

    btn_close_json = ft.ElevatedButton(
        "Fechar via JSON",
        icon=ft.Icons.PLAYLIST_ADD_CHECK,
        color="white",
        bgcolor="green",
        visible=False,
        tooltip="Fecha cada subtarefa do JSON com suas notas e arquivos",
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
                "1. Digite a Sprint Pai. 2. Busque as subtarefas. 3. Feche uma (dropdown) ou várias (JSON).",
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
            json_container,
            ft.Row([btn_close_json], alignment=ft.MainAxisAlignment.END, width=600),
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

    def _set_batch_ui_visible(visible: bool):
        dropdown_subtasks.visible = visible
        upload_container.visible = visible
        txt_notas.visible = visible
        btn_close_task.visible = visible
        btn_copy_ids.visible = visible
        btn_fill_json_template.visible = visible
        json_container.visible = visible
        btn_close_json.visible = visible

    # ==========================================
    # LOGIC
    # ==========================================
    def sync_ui():
        if app_state["session"]:
            lbl_logged_in.value = app_state["user"]
        else:
            txt_parent_id.value = ""
            txt_notas.value = ""
            txt_close_json.value = ""
            dropdown_subtasks.options = []
            dropdown_subtasks.value = None
            cached_subtasks.clear()
            _set_batch_ui_visible(False)
            lbl_form_error.visible = False
            selected_files.clear()
            update_file_list_ui()

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
                _set_batch_ui_visible(True)
                lbl_form_error.visible = False
            else:
                _set_batch_ui_visible(False)
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

    sync_ui()

    return ft.Tab(
        text="Fechar Tarefas",
        icon=ft.Icons.CHECKLIST,
        content=ft.Container(content=task_view, padding=20, expand=True),
    )

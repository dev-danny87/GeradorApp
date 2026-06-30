# tab_close_tasks.py
import flet as ft
from threading import Thread
from task_automation import get_redmine_subtasks, close_single_subtask

def create_close_tasks_tab(page: ft.Page, app_state, set_auth, sync_callbacks):
    selected_files = []

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
    # VIEW: TASK CLOSING (Now the only view here)
    # ==========================================
    lbl_logged_in = ft.Text("", color="green", weight=ft.FontWeight.BOLD, size=14)
    lbl_form_error = ft.Text("", color="red", visible=False, weight=ft.FontWeight.BOLD)

    txt_parent_id = ft.TextField(label="ID da Sprint (Pai)", width=200, hint_text="Ex: 33110", icon=ft.Icons.ACCOUNT_TREE)
    btn_search = ft.ElevatedButton("Buscar Subtarefas", icon=ft.Icons.SEARCH)
    search_progress = ft.ProgressRing(visible=False, width=20, height=20)

    dropdown_subtasks = ft.Dropdown(label="Selecione a Subtarefa para Fechar", width=600, visible=False)

    btn_pick_file = ft.ElevatedButton("Adicionar Evidências", icon=ft.Icons.ADD_PHOTO_ALTERNATE, on_click=lambda _: file_picker.pick_files(allow_multiple=True))
    btn_close_task = ft.ElevatedButton("Finalizar Subtarefa Escolhida", icon=ft.Icons.DONE, color="white", bgcolor="green", visible=False)

    user_header = ft.Row([
        ft.Icon(ft.Icons.PERSON, color="green", size=20),
        lbl_logged_in,
        ft.IconButton(icon=ft.Icons.LOGOUT, icon_color="red", icon_size=20, tooltip="Sair da conta", on_click=lambda e: set_auth(None, None))
    ], alignment=ft.MainAxisAlignment.END)

    upload_container = ft.Container(
        content=ft.Column([
            btn_pick_file,
            ft.Divider(height=10, color="transparent"),
            files_list_view
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        padding=20, border=ft.border.all(1, ft.Colors.OUTLINE), border_radius=10, visible=False, width=600
    )

    task_view = ft.Column([
        user_header,
        ft.Text("1. Digite a Sprint Pai. 2. Escolha a Subtarefa. 3. Adicione evidências.", weight=ft.FontWeight.BOLD),
        ft.Row([txt_parent_id, btn_search, search_progress], alignment=ft.MainAxisAlignment.CENTER),
        ft.Divider(height=15, color="transparent"),
        dropdown_subtasks,
        upload_container,
        lbl_form_error,
        ft.Row([btn_close_task], alignment=ft.MainAxisAlignment.END)
    ], alignment=ft.MainAxisAlignment.START, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=15, expand=True)

    # ==========================================
    # LOGIC
    # ==========================================
    def sync_ui():
        # Clean up form on logout or refresh username on login
        if app_state["session"]:
            lbl_logged_in.value = app_state["user"]
        else:
            txt_parent_id.value = ""
            dropdown_subtasks.visible = False
            upload_container.visible = False
            btn_close_task.visible = False
            selected_files.clear()
            update_file_list_ui()

    sync_callbacks.append(sync_ui)

    def handle_search(e):
        parent_id = txt_parent_id.value.strip()
        if not parent_id: return

        btn_search.disabled = True
        search_progress.visible = True
        page.update()

        def bg_search():
            subs = get_redmine_subtasks(app_state["session"], parent_id)
            if subs:
                dropdown_subtasks.options = [ft.dropdown.Option(key=s["id"], text=f"{s['id']} - {s['title']}") for s in subs]
                dropdown_subtasks.visible = True
                upload_container.visible = True
                btn_close_task.visible = True
                lbl_form_error.visible = False
            else:
                lbl_form_error.value = "Nenhuma subtarefa encontrada."
                lbl_form_error.visible = True

            btn_search.disabled = False
            search_progress.visible = False
            page.update()

        Thread(target=bg_search, daemon=True).start()

    def handle_close(e):
        sub_id = dropdown_subtasks.value
        if not sub_id:
            lbl_form_error.value = "Selecione uma subtarefa na lista."
            lbl_form_error.visible = True
            page.update()
            return

        lbl_form_error.visible = False
        page.update()

        files_to_upload = list(selected_files)
        selected_files.clear()
        update_file_list_ui()

        Thread(target=close_single_subtask, args=(app_state["session"], sub_id, files_to_upload), daemon=True).start()

    btn_search.on_click = handle_search
    btn_close_task.on_click = handle_close

    # Run once to initialize
    sync_ui()

    return ft.Tab(
        text="Fechar Tarefas", icon=ft.Icons.CHECKLIST,
        content=ft.Container(content=task_view, padding=20, expand=True)
    )
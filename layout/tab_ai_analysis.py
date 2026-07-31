# tab_ai_analysis.py
import flet as ft
import os
import datetime
import calendar
import json
from threading import Thread, Event

from services.ai_api_request import analyze_diffs_grouped_with_claude, MODEL_CONFIGS
from diff_task_automation import create_ai_redmine_tasks
from utils.ai_tasks_store import list_saved_results, load_tasks, save_results

DIFFS_ROOT = os.path.join(".", "diffs")


def create_ai_analysis_tab(app_state, set_auth, sync_callbacks, diffs_listeners=None):
    lbl_logged_in = ft.Text("", color="green", weight=ft.FontWeight.BOLD, size=14)
    lbl_status = ft.Text("", visible=False, weight=ft.FontWeight.BOLD)
    progress_ring = ft.ProgressRing(visible=False, width=20, height=20)

    stop_event = Event()

    dropdown_folders = ft.Dropdown(label="Pasta de Diffs Exportados", width=350)

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

    wrapper_ai_box = ft.Container(
        content=ft.Column([
            ft.Text("Análise Inteligente e Geração de Tarefas", weight=ft.FontWeight.BOLD, size=15, color="purple"),
            ft.Row([dropdown_model, dropdown_folders, txt_ai_hours], alignment=ft.MainAxisAlignment.START, wrap=True),
            ft.Row([btn_process_ai, btn_stop_ai], alignment=ft.MainAxisAlignment.START, wrap=True),
            ft.Divider(),
            ft.Row([dropdown_results, btn_create_redmine_tasks], alignment=ft.MainAxisAlignment.START, wrap=True),
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
            subfolders = [
                sub for sub in os.listdir(folder_path)
                if os.path.isdir(os.path.join(folder_path, sub))
            ]
            display_text = f"{folder} (Contém {len(subfolders)} subpasta(s))" if subfolders else folder
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

        btn_create_redmine_tasks.disabled = True
        progress_ring.visible = True
        show_status("Lendo respostas da IA e formatando tarefas...", "blue")
        _refresh_ui()

        def bg_create():
            try:
                subtasks_list = load_tasks(results_path)

                if not subtasks_list:
                    show_status("Nenhuma tarefa pôde ser extraída do arquivo de resultados.", "red")
                    return

                agora = datetime.datetime.now()
                start_date = agora.replace(day=1).strftime("%Y-%m-%d")
                end_date = agora.replace(day=calendar.monthrange(agora.year, agora.month)[1]).strftime("%Y-%m-%d")

                show_status(f"Criando Tarefa Pai e {len(subtasks_list)} subtarefas. Verifique o console.", "blue")
                _refresh_ui()

                create_ai_redmine_tasks(
                    app_state["session"],
                    start_date,
                    end_date,
                    app_state["user"],
                    subtasks_list,
                )
                show_status("Processo de criação no Redmine finalizado!", "green")

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

                diff_items = []
                for filename in sorted(os.listdir(target_dir)):
                    if not filename.endswith(".txt"):
                        continue
                    file_path = os.path.join(target_dir, filename)
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                    if content:
                        diff_items.append((filename, content))

                if not diff_items:
                    show_status(f"Nenhum conteúdo válido de diff encontrado em {folder_name}", "red")
                    return

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
        else:
            lbl_status.visible = False
            txt_ai_hours.value = ""

    sync_callbacks.append(sync_ui)

    def on_diffs_changed():
        refresh_ai_folders()
        _refresh_ui()

    if diffs_listeners is not None:
        diffs_listeners.append(on_diffs_changed)

    sync_ui()

    return ft.Tab(
        text="Análise com IA",
        icon=ft.Icons.AUTO_AWESOME,
        content=ft.Container(content=ai_view, padding=20, expand=True),
    )

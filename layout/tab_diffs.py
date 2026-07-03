import flet as ft
import os
import datetime
import calendar
import json
from threading import Thread

from utils.ui_components import DatePickerField
from utils.month_selector import (
    apply_month_to_date_pickers,
    create_month_shortcut_dropdown,
    current_month_key,
    month_bounds,
)
from services.gitlab_service import fetch_accessible_projects, extract_project_diff_for_day
from services.github_service import fetch_accessible_repositories, extract_repo_diff_for_day
from services.ai_api_request import analyze_diffs_grouped_with_claude, MODEL_CONFIGS
from diff_task_automation import create_ai_redmine_tasks


def _results_file_path(folder_name: str) -> str:
    return os.path.join(".", "diffs", folder_name, "ai_tasks_result.json")


def _legacy_results_file_path(folder_name: str) -> str:
    return os.path.join(".", "diffs", folder_name, "ai_tasks_result.jsonl")


def _load_tasks_from_results(folder_name: str) -> list:
    results_file = _results_file_path(folder_name)
    if os.path.exists(results_file):
        with open(results_file, "r", encoding="utf-8") as f:
            parsed_payload = json.load(f)
        tasks = parsed_payload.get("tasks", [])
        if not tasks:
            raise ValueError("O JSON retornado não possui a lista de 'tasks' esperada.")
        return tasks

    legacy_file = _legacy_results_file_path(folder_name)
    if not os.path.exists(legacy_file):
        raise FileNotFoundError("Arquivo de resultados não encontrado.")

    subtasks_list = []
    with open(legacy_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            batch_obj = json.loads(line)
            result_meta = batch_obj.get("result", {})
            if result_meta.get("type") != "succeeded":
                error_info = result_meta.get("error", {}).get("message", "Erro desconhecido retornado pela API")
                raise ValueError(f"O processamento da API falhou: {error_info}")

            raw_content = result_meta["message"]["content"][0]["text"].strip()
            if "```json" in raw_content:
                raw_content = raw_content.split("```json")[-1].split("```")[0].strip()
            elif raw_content.startswith("```"):
                raw_content = raw_content.strip("`").strip()

            parsed_payload = json.loads(raw_content)
            tasks = parsed_payload.get("tasks", [])
            if not tasks:
                raise ValueError("O JSON retornado não possui a lista de 'tasks' esperada.")
            subtasks_list.extend(tasks)

    return subtasks_list


def create_diffs_tab(app_state, set_auth, sync_callbacks):
    lbl_logged_in = ft.Text("", color="green", weight=ft.FontWeight.BOLD, size=14)
    lbl_status = ft.Text("", visible=False, weight=ft.FontWeight.BOLD)
    progress_ring = ft.ProgressRing(visible=False, width=20, height=20)

    hoje = datetime.datetime.now().date()
    inicio_mes, fim_mes = month_bounds(hoje)

    txt_author = ft.TextField(label="Autor (Username)", width=300, icon=ft.Icons.PERSON_SEARCH)
    date_start = DatePickerField(label="Data Inicial", default_date=inicio_mes, width=180)
    date_end = DatePickerField(label="Data Final", default_date=fim_mes, width=180, icon=ft.Icons.EVENT)

    def on_month_change(e):
        if not dropdown_month.value:
            return
        apply_month_to_date_pickers(dropdown_month.value, date_start, date_end)
        if date_start.page:
            date_start.update()
            date_end.update()

    dropdown_month = create_month_shortcut_dropdown(
        on_month_change,
        value=current_month_key(hoje),
    )

    dropdown_platform = ft.Dropdown(
        label="Plataforma",
        width=200,
        options=[
            ft.dropdown.Option(key="gitlab", text="GitLab"),
            ft.dropdown.Option(key="github", text="GitHub"),
        ],
        value="gitlab",
    )

    dropdown_repository = ft.Dropdown(
        label="Repositório",
        width=500,
        options=[],
    )

    btn_load_repositories = ft.ElevatedButton(
        "Carregar Repositórios",
        icon=ft.Icons.FOLDER_OPEN,
        color="white",
        bgcolor="orange",
    )
    btn_execute_diff = ft.ElevatedButton(
        "Extrair Diffs",
        icon=ft.Icons.CODE,
        color="white",
        bgcolor="blue",
        visible=False,
    )

    # --- COMPONENTES DA IA ---
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
            ft.Row([btn_process_ai, btn_create_redmine_tasks], alignment=ft.MainAxisAlignment.START, wrap=True),
        ]),
        padding=15,
        border=ft.border.all(1, ft.Colors.PURPLE_300),
        border_radius=10,
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
            on_click=lambda e: set_auth(None, None, False),
        ),
    ], alignment=ft.MainAxisAlignment.END)

    diffs_view = ft.Column([
        user_header,
        ft.Text("Extração de Modificações por Repositório Escolhido", size=16, weight=ft.FontWeight.BOLD),
        ft.Row([txt_author], alignment=ft.MainAxisAlignment.CENTER),
        ft.Row([dropdown_month], alignment=ft.MainAxisAlignment.CENTER),
        ft.Row(
            [date_start, date_end],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=20,
            tight=True,
        ),
        ft.Row(
            [dropdown_platform, dropdown_repository],
            alignment=ft.MainAxisAlignment.CENTER,
            wrap=True,
            spacing=15,
        ),
        ft.Row([btn_load_repositories, btn_execute_diff, progress_ring], alignment=ft.MainAxisAlignment.CENTER, wrap=True),
        wrapper_ai_box,
        lbl_status,
    ], alignment=ft.MainAxisAlignment.START, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=15, expand=True,
        scroll=ft.ScrollMode.AUTO)

    def show_status(text: str, color: str):
        lbl_status.value = text
        lbl_status.color = color
        lbl_status.visible = True

    def _clear_repository_selection():
        dropdown_repository.options.clear()
        dropdown_repository.value = None
        btn_execute_diff.visible = False

    def on_platform_change(e):
        _clear_repository_selection()
        if diffs_view.page:
            diffs_view.update()

    dropdown_platform.on_change = on_platform_change

    def on_repository_change(e):
        btn_execute_diff.visible = bool(dropdown_repository.value)
        if diffs_view.page:
            diffs_view.update()

    dropdown_repository.on_change = on_repository_change

    def handle_folder_change(e):
        folder_name = dropdown_folders.value
        if folder_name:
            results_file = _results_file_path(folder_name)
            legacy_file = _legacy_results_file_path(folder_name)
            btn_create_redmine_tasks.visible = os.path.exists(results_file) or os.path.exists(legacy_file)
        else:
            btn_create_redmine_tasks.visible = False
        diffs_view.update()

    dropdown_folders.on_change = handle_folder_change

    def handle_create_redmine_tasks(e):
        folder_name = dropdown_folders.value
        if not folder_name:
            show_status("Selecione uma pasta de diffs.", "red")
            return

        btn_create_redmine_tasks.disabled = True
        progress_ring.visible = True
        show_status("Lendo respostas da IA e formatando tarefas...", "blue")
        diffs_view.update()

        def bg_create():
            try:
                subtasks_list = _load_tasks_from_results(folder_name)

                if not subtasks_list:
                    show_status("Nenhuma tarefa pôde ser extraída do arquivo de resultados.", "red")
                    return

                agora = datetime.datetime.now()
                start_date = agora.replace(day=1).strftime("%Y-%m-%d")
                end_date = agora.replace(day=calendar.monthrange(agora.year, agora.month)[1]).strftime("%Y-%m-%d")

                show_status(f"Criando Tarefa Pai e {len(subtasks_list)} subtarefas. Verifique o console.", "blue")
                diffs_view.update()

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
                diffs_view.update()

        Thread(target=bg_create, daemon=True).start()

    btn_create_redmine_tasks.on_click = handle_create_redmine_tasks

    def refresh_ai_folders():
        diffs_dir = os.path.join(".", "diffs")
        dropdown_folders.options.clear()

        has_folders = False
        if os.path.exists(diffs_dir):
            folders = [f for f in os.listdir(diffs_dir) if os.path.isdir(os.path.join(diffs_dir, f))]
            if folders:
                for folder in sorted(folders, reverse=True):
                    folder_path = os.path.join(diffs_dir, folder)
                    subfolders = [
                        sub for sub in os.listdir(folder_path)
                        if os.path.isdir(os.path.join(folder_path, sub))
                    ]

                    display_text = f"{folder} (Contém {len(subfolders)} subpasta(s))" if subfolders else folder
                    dropdown_folders.options.append(ft.dropdown.Option(key=folder, text=display_text))
                has_folders = True

        wrapper_ai_box.visible = has_folders
        if diffs_view.page:
            diffs_view.update()

    def handle_load_repositories(e):
        platform = dropdown_platform.value
        if not platform:
            show_status("Selecione uma plataforma.", "red")
            return

        btn_load_repositories.disabled = True
        progress_ring.visible = True
        show_status(f"Carregando repositórios ({platform})...", "blue")
        diffs_view.update()

        def bg_load():
            try:
                if platform == "gitlab":
                    repos = fetch_accessible_projects()
                    dropdown_repository.options = [
                        ft.dropdown.Option(key=str(repo["id"]), text=repo["name"])
                        for repo in repos
                    ]
                else:
                    repos = fetch_accessible_repositories()
                    dropdown_repository.options = [
                        ft.dropdown.Option(key=repo["full_name"], text=repo["name"])
                        for repo in repos
                    ]

                if repos:
                    dropdown_repository.value = (
                        str(repos[0]["id"]) if platform == "gitlab" else repos[0]["full_name"]
                    )
                    btn_execute_diff.visible = True
                    show_status(f"{len(repos)} repositório(s) carregado(s).", "green")
                else:
                    dropdown_repository.value = None
                    btn_execute_diff.visible = False
                    show_status("Nenhum repositório encontrado para o token configurado.", "orange")

            except Exception as ex:
                _clear_repository_selection()
                show_status(f"Falha ao carregar repositórios: {str(ex)}", "red")
            finally:
                btn_load_repositories.disabled = False
                progress_ring.visible = False
                diffs_view.update()

        Thread(target=bg_load, daemon=True).start()

    def handle_execute_diff(e):
        platform = dropdown_platform.value
        repository = dropdown_repository.value
        author = txt_author.value.strip()

        if not platform:
            show_status("Selecione uma plataforma.", "red")
            return
        if not repository:
            show_status("Selecione um repositório.", "red")
            return
        if not author:
            show_status("Preencha o autor para prosseguir.", "red")
            return

        try:
            start_date = datetime.datetime.strptime(date_start.value.strip(), "%Y-%m-%d").date()
            end_date = datetime.datetime.strptime(date_end.value.strip(), "%Y-%m-%d").date()
        except ValueError:
            show_status("Formato de data inválido.", "red")
            return

        btn_execute_diff.disabled = True
        progress_ring.visible = True
        diffs_view.update()

        def bg_extract():
            try:
                timestamp_agora = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                folder_name = f"Diffs_Filtro_{author}_{timestamp_agora}"
                output_dir = os.path.join(".", "diffs", folder_name)
                os.makedirs(output_dir, exist_ok=True)

                delta = end_date - start_date
                for i in range(delta.days + 1):
                    current_date_str = (start_date + datetime.timedelta(days=i)).strftime("%Y-%m-%d")
                    show_status(f"Compilando arquivos do dia {current_date_str}...", "blue")
                    diffs_view.update()

                    if platform == "gitlab":
                        diff_content = extract_project_diff_for_day(
                            author, current_date_str, [int(repository)]
                        )
                    else:
                        diff_content = extract_repo_diff_for_day(
                            author, current_date_str, repository
                        )

                    if diff_content is None:
                        continue

                    file_path = os.path.join(output_dir, f"diff_{current_date_str}.txt")
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(diff_content)

                show_status(f"Sucesso! Diff exportado para:\n{output_dir}", "green")
                refresh_ai_folders()
            except Exception as ex:
                show_status(f"Erro ao extrair diffs: {str(ex)}", "red")
            finally:
                btn_execute_diff.disabled = False
                progress_ring.visible = False
                diffs_view.update()

        Thread(target=bg_extract, daemon=True).start()

    def handle_process_ai(e):
        selected_model = dropdown_model.value
        folder_name = dropdown_folders.value
        hours_str = txt_ai_hours.value.strip()

        if not selected_model:
            show_status("Selecione um Modelo de IA.", "red")
            return
        if not folder_name:
            show_status("Selecione uma pasta de diffs.", "red")
            return
        if not hours_str:
            show_status("Insira o total de horas.", "red")
            return

        try:
            total_hours = float(hours_str)
        except ValueError:
            show_status("Valor de horas inválido.", "red")
            return

        btn_process_ai.disabled = True
        progress_ring.visible = True
        show_status(f"Iniciando processamento agrupado ({selected_model})...", "purple")
        diffs_view.update()

        def prepare_directory_for_new_run(folder_path: str):
            files_to_remove = [
                "batch_info.json",
                "ai_tasks_result.jsonl",
                "ai_tasks_result.json",
                "ai_tasks_checkpoint.json",
            ]
            for filename in files_to_remove:
                file_path = os.path.join(folder_path, filename)
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"[CLEANUP] Arquivo antigo removido: {filename}")

        def bg_ai_process():
            try:
                target_dir = os.path.join(".", "diffs", folder_name)
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
                    diffs_view.update()

                final_payload = analyze_diffs_grouped_with_claude(
                    diff_items,
                    total_hours,
                    selected_model,
                    on_progress=on_progress,
                    output_dir=target_dir,
                )

                results_file = _results_file_path(folder_name)
                with open(results_file, "w", encoding="utf-8") as f:
                    json.dump(final_payload, f, ensure_ascii=False, indent=2)

                task_count = len(final_payload.get("tasks", []))
                show_status(
                    f"Processamento concluído! {task_count} tarefa(s) salvas em: {results_file}",
                    "green",
                )
                btn_create_redmine_tasks.visible = True

            except Exception as ex:
                show_status(f"Erro no processamento com IA: {str(ex)}", "red")
            finally:
                btn_process_ai.disabled = False
                progress_ring.visible = False
                diffs_view.update()

        Thread(target=bg_ai_process, daemon=True).start()

    def sync_ui():
        refresh_ai_folders()
        if app_state["session"]:
            lbl_logged_in.value = app_state["user"]
            if not txt_author.value:
                txt_author.value = app_state["user"]
        else:
            lbl_status.visible = False
            btn_execute_diff.visible = False
            btn_create_redmine_tasks.visible = False
            txt_author.value = ""
            _clear_repository_selection()

    sync_callbacks.append(sync_ui)

    btn_load_repositories.on_click = handle_load_repositories
    btn_execute_diff.on_click = handle_execute_diff
    btn_process_ai.on_click = handle_process_ai

    sync_ui()

    return ft.Tab(
        text="Extrair Diffs",
        icon=ft.Icons.CODE_OFF,
        content=ft.Container(content=diffs_view, padding=20, expand=True),
    )

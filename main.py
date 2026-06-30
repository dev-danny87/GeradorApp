from threading import Thread

import flet as ft
import sys
import os
import datetime
import locale
import re
import time
import unicodedata
import urllib.parse
import requests
from bs4 import BeautifulSoup
import pandas as pd

from layout.tab_evidences import create_evidences_tab
from layout.tab_evidences_pge import create_evidences_pge_tab
from layout.tab_tasks import create_tasks_tab
from layout.tab_close_tasks import create_close_tasks_tab
from layout.tab_diffs import create_diffs_tab
from services.auth_service import login_redmine, SSP_BASE_URL, PGE_BASE_URL
from services.pge_evidence_service import generate_evidences_pge, set_app_run as set_pge_app_run

VERSION = "evidences-v2.1-2025-09-12"


def _boot_banner():
    try:
        sys.__stdout__.write(f"[BOOT] {VERSION} from {os.path.abspath(__file__)}\n")
    except Exception:
        pass


_boot_banner()

# ==============================
# Constants and Configuration
# ==============================
DEBUG_PARSER = True
BASE_URL = "https://redmine.ssp.go.gov.br"
URL_REDINE_ISSUES = f"{BASE_URL}/issues?"
URL_ISSUE = f"{BASE_URL}/issues"

URL_PDF_GERAL = f"{BASE_URL}/issues.pdf?query_id="
URL_CSV_GERAL = f"{BASE_URL}/issues.csv?query_id="

EXT_RELATORIO = ".pdf"
EXT_CSV = ".csv"

RELATORIO_PDF_NOME = "RelatorioAtividadesGeradas.pdf"
RELATORIO_CSV_NOME = "ISSUES_GERAL.csv"

pd.set_option("display.max_rows", 50)
pd.set_option("display.max_columns", 50)
pd.set_option("display.width", 100000)

app_page = None
app_run = True


# ==============================
# Utilities
# ==============================
def clear():
    try:
        os.system("cls" if os.name == "nt" else "clear")
    except Exception:
        pass


def safe_mkdir(path: str):
    os.makedirs(path, exist_ok=True)


def timestamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_dirname(name: str) -> str:
    if name is None: return "desconhecido"
    name = str(name).strip()
    name = urllib.parse.unquote(name)
    name = unicodedata.normalize("NFKD", name)
    name = "".join([c for c in name if not unicodedata.combining(c)])
    name = re.sub(r"[^a-zA-Z0-9 \-\_\(\)\.\,]", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:150] if len(name) > 150 else name


def get_valid_filename(filename: str) -> str:
    if not filename: return "arquivo"
    name = urllib.parse.unquote(str(filename))
    name = unicodedata.normalize("NFKD", name)
    name = "".join([c for c in name if not unicodedata.combining(c)])
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name)
    name = name.strip().strip(".")
    return name[-150:]


def safe_str_to_float(s_value, *, _debug=DEBUG_PARSER) -> float:
    if s_value is None: return 0.0
    try:
        orig = str(s_value)
        s = orig.strip().replace("\xa0", "").replace(" ", "")
        if "," in s and "." in s:
            s_norm = s.replace(".", "").replace(",", ".")
        elif "," in s:
            s_norm = s.replace(",", ".")
        else:
            s_norm = s
        out = float(s_norm) if s_norm else 0.0
        return out
    except (ValueError, TypeError) as e:
        return 0.0


def http_get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    if "timeout" not in kwargs:
        kwargs["timeout"] = 60
    r = session.get(url, **kwargs)
    r.raise_for_status()
    return r


def _filename_from_content_disposition(cd: str) -> str | None:
    if not cd: return None
    m = re.search(r"filename\*\s*=\s*UTF-8''([^;]+)", cd, flags=re.IGNORECASE)
    if m: return urllib.parse.unquote(m.group(1))
    m = re.search(r'filename\s*=\s*"([^"]+)"', cd, flags=re.IGNORECASE)
    if m: return m.group(1)
    m = re.search(r'filename\s*=\s*([^;]+)', cd, flags=re.IGNORECASE)
    if m: return m.group(1).strip()
    return None


def download_file(session: requests.Session, url: str, dest_path: str, max_retries: int = 3):
    dest_dir = os.path.dirname(dest_path)
    safe_mkdir(dest_dir)
    last_exc = None

    def _looks_like_id(name: str) -> bool:
        return ('.' not in name) or bool(re.fullmatch(r'\d+', name))

    for attempt in range(1, max_retries + 1):
        try:
            with session.get(url, stream=True, timeout=120, allow_redirects=True) as r:
                r.raise_for_status()
                cd = r.headers.get("Content-Disposition", "")
                suggested = _filename_from_content_disposition(cd)
                if not suggested:
                    final_path = urllib.parse.urlparse(r.url).path
                    suggested = os.path.basename(final_path)
                if suggested:
                    suggested = get_valid_filename(urllib.parse.unquote(suggested))
                base = os.path.basename(dest_path)
                if suggested and _looks_like_id(base):
                    final_dest = os.path.join(dest_dir, suggested)
                else:
                    final_dest = dest_path

                with open(final_dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=512 * 1024):
                        if chunk: f.write(chunk)
            print(f"[{timestamp()}] OK: {url} -> {final_dest}")
            return
        except Exception as e:
            last_exc = e
            print(f"[{timestamp()}] WARN: download attempt {attempt}/{max_retries} failed for {url}: {e}")
            time.sleep(1.5 * attempt)
    print(f"[{timestamp()}] ERROR: failed to download {url} to {dest_path}: {last_exc}")


# ==============================
# Core Logic
# ==============================
# ADICIONADO: O argumento `session` foi injetado aqui
def generate_evidences(session, strPathRedmineQueryId: str, projeto: str, exception: str):
    project_id_map = {
        "hpm": "pm-130-2022",
        "procon-go": "procon-go",
        "geral": "",
    }
    project_slug = project_id_map.get(exception, "")
    has_project = bool(project_slug)

    if has_project:
        base_list_url = f"{BASE_URL}/projects/{project_slug}/issues?"
        url_get_issue_list = f"{BASE_URL}/projects/{project_slug}/issues?page=1&query_id="
        url_pdf_geral = f"{BASE_URL}/projects/{project_slug}/issues.pdf?query_id="
        url_csv_geral = f"{BASE_URL}/projects/{project_slug}/issues.csv?query_id="
    else:
        base_list_url = URL_REDINE_ISSUES
        url_get_issue_list = f"{BASE_URL}/issues?page=1&query_id="
        url_pdf_geral = URL_PDF_GERAL
        url_csv_geral = URL_CSV_GERAL

    try:
        locale.setlocale(locale.LC_ALL, "pt_BR.UTF-8")
    except Exception:
        pass

    month_year = datetime.date.today().strftime("%B_%Y").capitalize()
    folder_stamp = datetime.date.today().strftime("%d-%m") + "-" + time.strftime("%H_%M")
    base_out_dir = os.path.join(".", "Relatórios", f"Evidencias_{projeto}", month_year, folder_stamp)
    safe_mkdir(base_out_dir)

    def get_redmine_page(session: requests.Session, page_num: int):
        full_url = f"{base_list_url}page={page_num}&query_id={strPathRedmineQueryId}"
        print(f"[{timestamp()}] Fetching page {page_num}: {full_url}")
        r = http_get(session, full_url)
        soup = BeautifulSoup(r.text, "html.parser")
        tags_no_data = soup.find_all("p", attrs={"class": "nodata"})
        return tags_no_data, soup

    def get_redmine_issue_attachments(session: requests.Session, issue_id: str):
        url = f"{URL_ISSUE}/{issue_id}"
        r = http_get(session, url)
        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        for a in soup.find_all("a", attrs={"class": "icon icon-attachment"}):
            href = a.get("href")
            text = _clean_link_text(a.get_text(strip=True))
            if href: results.append({"href": href, "name": text})
        return results

    clear()
    print(f"\n[{timestamp()}] Preparando para gerar evidências a partir do Redmine...")
    print(f"Query ID: {strPathRedmineQueryId} | Pasta de saída: {base_out_dir}")

    if not session:
        print(f"[{timestamp()}] ERROR: Sessão inválida. Faça login primeiro.")
        return

    class_name_assigned = "cf_5"
    issues_list = []
    nao_atribuidas = []

    global app_run
    app_run = True

    print(f"\n[{timestamp()}] Buscando informações no Redmine ({BASE_URL})")

    page_num = 1
    while app_run:
        tagsNoDataPage, soupPage = get_redmine_page(session, page_num)
        if tagsNoDataPage:
            print(f"[{timestamp()}] Page {page_num} has no data. Stopping.")
            break

        for tr in soupPage.find_all("tr"):
            if not app_run: break
            tr_id = tr.get("id", "")
            if not tr_id.startswith("issue-"): continue
            issue_id = tr_id.replace("issue-", "").strip()
            if not issue_id.isdigit(): continue

            td_assigned = tr.find("td", attrs={"class": class_name_assigned})
            assigned_to = td_assigned.get_text(strip=True) if td_assigned else ""

            td_subject = tr.find("td", attrs={"class": "subject"})
            subject_text = td_subject.get_text(" ", strip=True) if td_subject else ""

            td_hours = tr.find("td", attrs={"class": "total_spent_hours"})
            spent_hours_raw = td_hours.get_text(strip=True) if td_hours else ""
            spent_hours = safe_str_to_float(spent_hours_raw)

            if assigned_to:
                att_list = []
                anexos = get_redmine_issue_attachments(session, issue_id)
                for anexo in anexos:
                    if not app_run: break
                    att_list.append(anexo)

                issues_list.append({
                    "ID": issue_id,
                    "Atribuição": assigned_to,
                    "Descrição": subject_text,
                    "Horas gastas": spent_hours,
                    "Anexos": att_list,
                })
            else:
                nao_atribuidas.append(issue_id)

        page_num += 1

    if len(issues_list) == 0:
        print(f"[{timestamp()}] Nenhuma Issue para gerar. Encerrando.")
        return

    df = pd.DataFrame(issues_list)
    print(f"\n[{timestamp()}] Tarefas encontradas: {len(issues_list)}")

    df_sorted = df.sort_values(["Atribuição", "ID"])

    print(f"\n[{timestamp()}] Gerando evidências (PDFs e anexos por tarefa)...")
    for _, row in df_sorted.iterrows():
        if not app_run:
            print(f"[{timestamp()}] Interrompido pelo usuário.")
            break

        atrib = safe_dirname(row["Atribuição"])
        out_dir_user = os.path.join(base_out_dir, atrib)
        safe_mkdir(out_dir_user)
        tarefa = row["ID"]

        url_pdf_issue = f"{URL_ISSUE}/{tarefa}{EXT_RELATORIO}"
        dest_pdf_issue = os.path.join(out_dir_user, f"{tarefa}{EXT_RELATORIO}")
        download_file(session, url_pdf_issue, dest_pdf_issue)

        attachments = row.get("Anexos") or []
        if attachments:
            att_dir = os.path.join(out_dir_user, tarefa)
            safe_mkdir(att_dir)
            for att in attachments:
                if not app_run: break
                if isinstance(att, dict):
                    href = att.get("href") or ""
                    text_name = att.get("name") or ""
                else:
                    href = str(att or "")
                    text_name = ""

                if not href: continue
                dl = f"{BASE_URL}{href}".replace("/attachments/", "/attachments/download/")
                name_guess = text_name if "." in text_name else os.path.basename(href)
                filename = get_valid_filename(name_guess) or "arquivo"
                dest = os.path.join(att_dir, filename)
                download_file(session, dl, dest)

    print(f"\n[{timestamp()}] Gerando PDF da consulta...")
    url_pdf_query = f"{url_pdf_geral}{strPathRedmineQueryId}"
    dest_pdf_query = os.path.join(base_out_dir, RELATORIO_PDF_NOME)
    download_file(session, url_pdf_query, dest_pdf_query)

    print(f"\n[{timestamp()}] Gerando CSV (issues) da consulta...")
    url_csv_query = f"{url_csv_geral}{strPathRedmineQueryId}"
    dest_csv_query = os.path.join(base_out_dir, RELATORIO_CSV_NOME)
    download_file(session, url_csv_query, dest_csv_query)

    print(f"\n[{timestamp()}] Realizando cálculos adicionais...")
    df_tot = (
        df.groupby("Atribuição", as_index=False)
        .agg(qtd_itens=("ID", "count"), horas_total=("Horas gastas", "sum"))
        .sort_values(["Atribuição"])
    )

    df.to_csv(os.path.join(base_out_dir, "tarefas.csv"), sep=";", index=False, encoding="utf-8-sig")
    df_tot.to_csv(os.path.join(base_out_dir, "tarefas_totalizadores.csv"), sep=";", index=False, encoding="utf-8-sig")

    if len(nao_atribuidas) > 0:
        pd.DataFrame({"ID": nao_atribuidas}).to_csv(
            os.path.join(base_out_dir, "tarefasNaoAtribuidas.csv"), sep=";", index=False, encoding="utf-8-sig"
        )
    print(f"\n[{timestamp()}] Fim! DIRETORIO_FINAL:{base_out_dir}")


def stop_process():
    print(f"[{timestamp()}] Processo interrompido pelo usuário.")
    global app_run
    app_run = False
    set_pge_app_run(False)


# ADICIONADO: O argumento `session` foi injetado aqui também
def generate_all_evidences(session):
    batch = [
        ("120", "contrato_hpm", "hpm"),
        ("83", "gerencia_inovacao", ""),
        ("84", "gerencia_inovacao_bi", ""),
        ("111", "gerencia_inteligencia_negocios", ""),
        ("85", "gerencia_telecomunicacao", ""),
        ("169", "procon-go", "procon-go"),
    ]
    for query_id, project_label, exception_type in batch:
        if not app_run:
            break
        print(f"\n[{timestamp()}] Iniciando geração para: {project_label}")
        generate_evidences(session, query_id, project_label, exception_type)
        time.sleep(2)


def _clean_link_text(s: str) -> str:
    return re.sub(r'\s+\([\d\.,]+\s*[KMG]?B\)$', '', s or '').strip()


# ==============================
# Flet App (UI)
# ==============================
class LogConsole:
    def __init__(self, page: ft.Page, max_lines: int = 2000, newest_on_top: bool = True):
        self.page = page
        self.max_lines = max_lines
        self.newest_on_top = newest_on_top
        self.view = ft.ListView(expand=True, spacing=2, auto_scroll=not newest_on_top)

    def write(self, message):
        if message and not message.isspace():
            text_line = ft.Text(message.strip(), size=13)

            if self.newest_on_top:
                self.view.controls.insert(0, text_line)
            else:
                self.view.controls.append(text_line)

            overflow = len(self.view.controls) - self.max_lines
            if overflow > 0:
                # Se for newest_on_top, os mais velhos estão no final (apaga do final)
                if self.newest_on_top:
                    del self.view.controls[-overflow:]
                # Senão, os mais velhos estão no topo (apaga do começo)
                else:
                    del self.view.controls[:overflow]

            if self.view.page:
                self.view.update()

    def flush(self):
        pass


def main(page: ft.Page) -> None:
    global app_page
    app_page = page
    app_page.title = "Gerador de Evidências e Tarefas Redmine"

    page.window.maximized = True
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.padding = 20
    app_page.vertical_alignment = ft.MainAxisAlignment.START
    app_page.horizontal_alignment = ft.MainAxisAlignment.CENTER

    console = LogConsole(page, newest_on_top=True)
    sys.stdout = console

    # GLOBAL STATE
    app_state = {
        "session": None,
        "user": None,
        "is_gestor": False,
        "redmine_host": "ssp",
        "base_url": SSP_BASE_URL,
        "pge_cf28_options": None,
    }
    sync_callbacks = []

    # ==========================================
    # CENTRALIZED LOGIN UI
    # ==========================================
    txt_username = ft.TextField(label="Usuário Redmine", width=300, icon=ft.Icons.PERSON)
    txt_password = ft.TextField(label="Senha", width=300, password=True, can_reveal_password=True, icon=ft.Icons.LOCK)
    login_progress = ft.ProgressRing(visible=False, width=20, height=20)
    login_error_text = ft.Text("", color="red", visible=False, weight=ft.FontWeight.BOLD)
    btn_login = ft.ElevatedButton("Fazer Login", icon=ft.Icons.LOGIN, bgcolor="blue", color="white")

    host_selection = {"value": "ssp"}
    host_subtitle = ft.Text("SSP (padrão)")

    def on_host_radio_change(e):
        host_selection["value"] = e.control.value
        host_subtitle.value = "PGE" if e.control.value == "pge" else "SSP (padrão)"
        page.update()

    host_selector = ft.ExpansionTile(
        title=ft.Text("Instância Redmine"),
        subtitle=host_subtitle,
        controls=[
            ft.RadioGroup(
                content=ft.Column([
                    ft.Radio(value="ssp", label="SSP (redmine.ssp.go.gov.br)"),
                    ft.Radio(value="pge", label="PGE (projetos.procuradoria.go.gov.br/contrato17)"),
                ]),
                value="ssp",
                on_change=on_host_radio_change,
            ),
        ],
        initially_expanded=False,
    )

    login_container = ft.Column([
        ft.Text("Acesso Seguro", size=30, weight=ft.FontWeight.BOLD),
        ft.Text("Faça login com sua conta do Redmine para acessar os recursos."),
        ft.Divider(height=20, color="transparent"),
        ft.Container(content=host_selector, width=300),
        txt_username,
        txt_password,
        ft.Row([btn_login, login_progress], alignment=ft.MainAxisAlignment.CENTER),
        login_error_text
    ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, expand=True)

    def handle_login(e):
        user, pwd = txt_username.value, txt_password.value
        if not user or not pwd: return

        # 1. Desabilita os campos PRIMEIRO
        txt_username.disabled = True
        txt_password.disabled = True
        btn_login.disabled = True
        login_progress.visible = True
        login_error_text.visible = False

        # 2. FORÇA a interface a atualizar e renderizar os campos cinzas/desabilitados
        page.update()

        def bg_login():
            host = host_selection["value"]
            base_url = PGE_BASE_URL if host == "pge" else SSP_BASE_URL
            session, result, is_gestor = login_redmine(user, pwd, base_url)

            txt_username.disabled = False
            txt_password.disabled = False
            btn_login.disabled = False
            login_progress.visible = False

            if session:
                if host == "pge" and not is_gestor:
                    session.close()
                    login_error_text.value = "Acesso negado: permissão de Gestor necessária para o PGE."
                    login_error_text.visible = True
                else:
                    set_auth(session, user, is_gestor, host, base_url)
            else:
                login_error_text.value = result
                login_error_text.visible = True

            page.update()

        # 5. INICIA A THREAD (Isso impede que o app congele)
        Thread(target=bg_login, daemon=True).start()

    btn_login.on_click = handle_login

    # ==========================================
    # MAIN APP UI (TABS & CONSOLE)
    # ==========================================
    def set_auth(session, user, is_gestor=False, redmine_host="ssp", base_url=SSP_BASE_URL):
        app_state["session"] = session
        app_state["user"] = user
        app_state["is_gestor"] = is_gestor
        app_state["redmine_host"] = redmine_host if session else "ssp"
        app_state["base_url"] = base_url if session else SSP_BASE_URL
        if not session:
            app_state["pge_cf28_options"] = None

        if session:
            login_container.visible = False
            main_app_container.visible = True

            if redmine_host == "pge" and is_gestor:
                tabs.tabs = [tab_evidences_pge]
            elif redmine_host == "ssp" and is_gestor:
                tabs.tabs = [tab_evidences, tab_tasks, tab_close, tab_diffs]
            else:
                tabs.tabs = [tab_tasks, tab_close, tab_diffs]
            tabs.selected_index = 0
        else:
            login_container.visible = True
            main_app_container.visible = False
            txt_password.value = ""
            login_error_text.visible = False

        for callback in sync_callbacks:
            callback()

        page.update()

    # Create Tabs
    tab_evidences = create_evidences_tab(
        on_generate=generate_evidences,
        on_generate_all=generate_all_evidences,
        on_stop=stop_process,
        get_timestamp=timestamp,
        app_state=app_state,
        set_auth=set_auth,
        sync_callbacks=sync_callbacks
    )

    tab_evidences_pge = create_evidences_pge_tab(
        on_generate=generate_evidences_pge,
        on_stop=stop_process,
        get_timestamp=timestamp,
        app_state=app_state,
        set_auth=set_auth,
        sync_callbacks=sync_callbacks,
    )

    tab_tasks = create_tasks_tab(app_state, set_auth, sync_callbacks)
    tab_close = create_close_tasks_tab(page, app_state, set_auth, sync_callbacks)
    tab_diffs = create_diffs_tab(app_state, set_auth, sync_callbacks)

    tabs = ft.Tabs(selected_index=0, animation_duration=300, tabs=[], expand=4)

    console.view.expand = 1

    def toggle_console(e):
        console.view.visible = not console.view.visible
        btn_toggle_console.icon = ft.Icons.KEYBOARD_ARROW_DOWN if console.view.visible else ft.Icons.KEYBOARD_ARROW_UP
        btn_toggle_console.tooltip = "Ocultar Console" if console.view.visible else "Mostrar Console"
        page.update()

    btn_toggle_console = ft.IconButton(
        icon=ft.Icons.KEYBOARD_ARROW_DOWN,
        tooltip="Ocultar Console",
        on_click=toggle_console
    )

    console_header = ft.Row(
        controls=[ft.Text("Console Log:", weight=ft.FontWeight.BOLD), btn_toggle_console],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN
    )

    main_app_container = ft.Column([
        tabs,
        ft.Divider(height=2, color="grey"),
        console_header,
        console.view
    ], visible=False, expand=True)  # Hidden until login

    # Add both containers to the page
    app_page.add(login_container, main_app_container)

    print(f"[{timestamp()}] Aplicação iniciada com sucesso. Faça o login para continuar.\n")


if __name__ == "__main__":
    ft.app(target=main)
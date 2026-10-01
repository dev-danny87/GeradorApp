from bs4 import BeautifulSoup
import datetime

from redmine_mappings import LOGIN_TO_USER_ID
from utils.redmine_version import get_dynamic_version

BASE_URL = "https://redmine.ssp.go.gov.br"


def _timestamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _get_issue_token(session):
    url_new_issue = f"{BASE_URL}/projects/item-01-inovacao/issues/new"
    r = session.get(url_new_issue, timeout=60)
    if "/login" in r.url or r.status_code == 403:
        raise PermissionError("Sua conta não tem permissão no projeto 'item-01-inovacao'.")
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    token_tag = soup.find("input", attrs={"name": "authenticity_token"})
    if not token_tag:
        raise ValueError("Token CSRF não encontrado na página de nova tarefa.")
    return token_tag.get("value")


def create_ai_redmine_tasks(
        session,
        start_date,
        due_date,
        username,
        tasks_list,
        *,
        sistema="SICOR",
        orgao_solicitante="PM",
        atribuicao_catalogo="Desenvolvedor Sênior",
        projeto_vinculado="SICOR",
        versao=None,
        desenvolvedor_id=None,
):
    user_id = LOGIN_TO_USER_ID.get(username, "")

    if not user_id:
        print(f"[{_timestamp()}] [ERRO] O usuário '{username}' não tem um ID mapeado em LOGIN_TO_USER_ID!")
        print(f"[{_timestamp()}] [ERRO] Abortando criação, o campo 'Atribuído para' é obrigatório no Redmine.")
        return None

    developer_id = (desenvolvedor_id or "").strip() or user_id
    if not developer_id:
        print(f"[{_timestamp()}] [ERRO] Nenhum Desenvolvedor selecionado.")
        print(f"[{_timestamp()}] [ERRO] Abortando criação, o campo 'Desenvolvedor' é obrigatório no Redmine.")
        return None

    try:
        data_obj = datetime.datetime.strptime(start_date, "%Y-%m-%d")
        mes_numero = data_obj.month
    except ValueError:
        mes_numero = datetime.datetime.now().month

    meses_ptbr = {
        1: "JANEIRO", 2: "FEVEREIRO", 3: "MARÇO", 4: "ABRIL",
        5: "MAIO", 6: "JUNHO", 7: "JULHO", 8: "AGOSTO",
        9: "SETEMBRO", 10: "OUTUBRO", 11: "NOVEMBRO", 12: "DEZEMBRO"
    }
    nome_mes = meses_ptbr.get(mes_numero, "MÊS")

    subject_dinamico = f"{sistema} - SPRINT {nome_mes}"
    description_dinamica = (
        f"Planejamento de tarefas técnicas e detalhamento de implementações "
        f"para a sprint de {nome_mes.lower()} baseadas nos diffs recentes."
    )
    fixed_version_id = versao or get_dynamic_version()

    print(f"\n[{_timestamp()}] ===============================================")
    print(f"[{_timestamp()}] INICIANDO CRIAÇÃO DE TAREFAS: {subject_dinamico}")
    print(f"[{_timestamp()}] Versão (fixed_version_id): {fixed_version_id}")
    print(f"[{_timestamp()}] ===============================================")

    try:
        # 1. CRIAR TAREFA PAI
        parent_token = _get_issue_token(session)

        parent_payload = {
            "utf8": "✓",
            "authenticity_token": parent_token,
            "form_update_triggered_by": "",
            "issue[is_private]": "0",
            "issue[project_id]": "16",
            "issue[tracker_id]": "8",
            "issue[subject]": subject_dinamico,
            "issue[description]": description_dinamica,
            "issue[status_id]": "1",
            "was_default_status": "1",
            "issue[priority_id]": "4",
            "issue[assigned_to_id]": user_id,
            "issue[fixed_version_id]": fixed_version_id,
            "issue[parent_issue_id]": "",
            "issue[start_date]": start_date,
            "issue[due_date]": due_date,
            "issue[estimated_hours]": "",
            "issue[custom_field_values][5]": developer_id,
            "issue[custom_field_values][10]": "12 - Implementação de Nova Funcionalidade do Tipo Interface de Usuário (backend e frontend)",
            "issue[custom_field_values][2]": "JAVA",
            "issue[custom_field_values][6]": sistema,
            "issue[custom_field_values][3]": orgao_solicitante,
            "issue[custom_field_values][4]": "ordem verbal",
            "issue[custom_field_values][7]": "0",
            "issue[custom_field_values][8]": "0",
            "issue[custom_field_values][22]": atribuicao_catalogo,
            "issue[custom_field_values][27]": projeto_vinculado,
            "issue[watcher_user_ids][]": "",
            "commit": "Criar"
        }

        url_post = f"{BASE_URL}/projects/item-01-inovacao/issues"
        r_parent = session.post(url_post, data=parent_payload, allow_redirects=True)

        if r_parent.status_code == 200 and "/issues/" in r_parent.url and "new" not in r_parent.url:
            parent_id = r_parent.url.split("?")[0].split("/")[-1]
            print(f"[{_timestamp()}] [OK] TAREFA PAI CRIADA! ID: {parent_id}")
        else:
            soup_erro = BeautifulSoup(r_parent.text, "html.parser")
            err_div = soup_erro.find("div", id="errorExplanation")
            if err_div:
                texto_erro = err_div.get_text(separator=' | ', strip=True)
                print(f"[{_timestamp()}] [FALHA] Tarefa Pai recusada pelo Redmine: {texto_erro}")
            else:
                print(f"[{_timestamp()}] [FALHA] Falha Crítica na Tarefa Pai! HTTP Status: {r_parent.status_code}")
                print(f"[{_timestamp()}] [HTML BRUTO]: {r_parent.text[:300].strip()}")
            return None

        created_subtasks: list[dict] = []

        # 2. CRIAR SUBTAREFAS
        if tasks_list:
            print(f"\n[{_timestamp()}] Processando {len(tasks_list)} subtarefas...")

            for index, subtask in enumerate(tasks_list):
                sub_title = subtask.get("task_title", f"Subtarefa {index + 1}")
                try:
                    sub_token = _get_issue_token(session)
                    category = subtask.get("category", "Feature")
                    base_desc = subtask.get("description", "Sem descrição detalhada.")

                    sub_desc = f"{base_desc}\n\n**Categoria:** {category.capitalize()}"
                    sub_hours = subtask.get("estimated_hours", "")

                    sub_payload = {
                        "utf8": "✓",
                        "authenticity_token": sub_token,
                        "form_update_triggered_by": "",
                        "issue[is_private]": "0",
                        "issue[project_id]": "16",
                        "issue[tracker_id]": "8",
                        "issue[subject]": sub_title,
                        "issue[description]": sub_desc,
                        "issue[status_id]": "1",
                        "was_default_status": "1",
                        "issue[priority_id]": "2",
                        "issue[assigned_to_id]": user_id,
                        "issue[fixed_version_id]": fixed_version_id,
                        "issue[parent_issue_id]": parent_id,
                        "issue[start_date]": start_date,
                        "issue[due_date]": due_date,
                        "issue[estimated_hours]": str(sub_hours),
                        "issue[custom_field_values][5]": developer_id,
                        "issue[custom_field_values][10]": "12 - Implementação de Nova Funcionalidade do Tipo Interface de Usuário (backend e frontend)",
                        "issue[custom_field_values][2]": "JAVA",
                        "issue[custom_field_values][6]": sistema,
                        "issue[custom_field_values][3]": orgao_solicitante,
                        "issue[custom_field_values][4]": "ordem verbal",
                        "issue[custom_field_values][7]": "0",
                        "issue[custom_field_values][8]": "0",
                        "issue[custom_field_values][22]": atribuicao_catalogo,
                        "issue[custom_field_values][27]": projeto_vinculado,
                        "issue[watcher_user_ids][]": "",
                        "commit": "Criar"
                    }

                    affected_files = subtask.get("affected_files", [])
                    for i, file_name in enumerate(affected_files):
                        sub_payload[f"issue[checklists_attributes][{i}][is_done]"] = "0"
                        sub_payload[f"issue[checklists_attributes][{i}][subject]"] = f"Modificado: {file_name}"
                        sub_payload[f"issue[checklists_attributes][{i}][_destroy]"] = "false"
                        sub_payload[f"issue[checklists_attributes][{i}][position]"] = str(i)
                        sub_payload[f"issue[checklists_attributes][{i}][is_section]"] = "false"
                        sub_payload[f"issue[checklists_attributes][{i}][id]"] = ""

                    r_sub = session.post(url_post, data=sub_payload, allow_redirects=True)

                    if r_sub.status_code == 200 and "/issues/" in r_sub.url and "new" not in r_sub.url:
                        sub_id = r_sub.url.split("?")[0].split("/")[-1]
                        print(f"[{_timestamp()}]  -> [OK] Subtarefa '{sub_title}' criada! ID: {sub_id} ({sub_hours}h)")
                        created_subtasks.append({
                            "id": sub_id,
                            "task_id": subtask.get("task_id"),
                            "title": sub_title,
                            "estimated_hours": sub_hours,
                            "commit_links": subtask.get("commit_links") or [],
                        })
                    else:
                        soup_sub_erro = BeautifulSoup(r_sub.text, "html.parser")
                        sub_err_div = soup_sub_erro.find("div", id="errorExplanation")
                        if sub_err_div:
                            texto_erro_sub = sub_err_div.get_text(separator=' | ', strip=True)
                            print(f"[{_timestamp()}]  -> [FALHA] {texto_erro_sub}")
                        else:
                            print(f"[{_timestamp()}]  -> [FALHA] HTTP Status: {r_sub.status_code}")

                except Exception as ex_sub:
                    print(f"[{_timestamp()}]  -> [ERRO] Falha interna na subtarefa '{sub_title}': {ex_sub}")

        print(f"\n[{_timestamp()}] PROCESSO DE SPRINT CONCLUÍDO!")
        return {"parent_id": parent_id, "subtasks": created_subtasks}

    except PermissionError as pe:
        print(f"[{_timestamp()}] {pe}")
        return None
    except Exception as e:
        print(f"[{_timestamp()}] ERRO CRÍTICO: {e}")
        return None

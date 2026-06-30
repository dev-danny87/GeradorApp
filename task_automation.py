import requests
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


def _custom_fields_payload(
        sistema: str,
        orgao_solicitante: str,
        atribuicao_catalogo: str,
        projeto_vinculado: str,
        notas: str,
) -> dict:
    payload = {
        "issue[custom_field_values][6]": sistema,
        "issue[custom_field_values][3]": orgao_solicitante,
        "issue[custom_field_values][22]": atribuicao_catalogo,
        "issue[custom_field_values][27]": projeto_vinculado,
    }
    if notas.strip():
        payload["issue[notes]"] = notas.strip()
    return payload


def create_redmine_issue(
        session,
        start_date,
        due_date,
        username,
        subtasks_list,
        *,
        sistema="SICOR",
        orgao_solicitante="PM",
        atribuicao_catalogo="Desenvolvedor Sênior",
        projeto_vinculado="SICOR",
        notas="",
        versao=None,
):
    user_id = LOGIN_TO_USER_ID.get(username, "")

    fixed_version_id = versao or get_dynamic_version()

    # CORREÇÃO 1: Evitar submissão se o ID do usuário for inválido/vazio
    if not user_id:
        print(f"[{_timestamp()}] [ERRO] O usuário '{username}' não tem um ID mapeado em LOGIN_TO_USER_ID!")
        print(f"[{_timestamp()}] [ERRO] Abortando criação, o campo 'Atribuído para' é obrigatório no Redmine.")
        return

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

    subject_dinamico = f"SICOR - SPRINT {nome_mes}"
    description_dinamica = f"tarefas criadas para a sprint de {nome_mes.lower()}"

    print(f"\n[{_timestamp()}] ===============================================")
    print(f"[{_timestamp()}] INICIANDO CRIAÇÃO: {subject_dinamico}")
    print(f"[{_timestamp()}] Versão (fixed_version_id): {fixed_version_id}")
    print(f"[{_timestamp()}] ===============================================")

    try:
        # -------------------------------------------------------------
        # 1. CRIAR A TAREFA PAI
        # -------------------------------------------------------------
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
            "issue[custom_field_values][5]": user_id,
            "issue[custom_field_values][10]": "12 - Implementação de Nova Funcionalidade do Tipo Interface de Usuário (backend e frontend)",
            "issue[custom_field_values][2]": "JAVA",
            "issue[custom_field_values][4]": "ordem verbal",
            "issue[custom_field_values][7]": "0",
            "issue[custom_field_values][8]": "0",
            "issue[watcher_user_ids][]": "",
            "commit": "Criar"
        }
        parent_payload.update(
            _custom_fields_payload(sistema, orgao_solicitante, atribuicao_catalogo, projeto_vinculado, notas)
        )

        url_post = f"{BASE_URL}/projects/item-01-inovacao/issues"
        r_parent = session.post(url_post, data=parent_payload, allow_redirects=True)

        if r_parent.status_code == 200 and "/issues/" in r_parent.url and "new" not in r_parent.url:
            parent_id = r_parent.url.split("?")[0].split("/")[-1]
            print(f"[{_timestamp()}] [OK] TAREFA PAI CRIADA! ID: {parent_id} - URL: {r_parent.url}")
        else:
            # CORREÇÃO 2: Extrair e mostrar o erro real da Tarefa Pai
            soup_erro = BeautifulSoup(r_parent.text, "html.parser")
            err_div = soup_erro.find("div", id="errorExplanation")
            if err_div:
                texto_erro = err_div.get_text(separator=' | ', strip=True)
                print(f"[{_timestamp()}] [FALHA] Tarefa Pai recusada pelo Redmine: {texto_erro}")
            else:
                print(f"[{_timestamp()}] [FALHA] Falha Crítica na Tarefa Pai! HTTP Status: {r_parent.status_code}")
                print(f"[{_timestamp()}] [HTML BRUTO]: {r_parent.text[:300].strip()}")
            return

        # -------------------------------------------------------------
        # 2. CRIAR AS SUBTAREFAS A PARTIR DO JSON
        # -------------------------------------------------------------
        if subtasks_list:
            print(f"\n[{_timestamp()}] Encontrado {len(subtasks_list)} subtarefas. Processando...")

            for index, subtask in enumerate(subtasks_list):
                try:
                    sub_token = _get_issue_token(session)

                    sub_title = subtask.get("task_title") or subtask.get("title", f"Subtarefa {index + 1}")
                    category = subtask.get("category", "Feature")
                    base_desc = subtask.get("description", "")
                    if category and "**Categoria:**" not in base_desc:
                        sub_desc = (
                            f"{base_desc}\n\n**Categoria:** {category.capitalize()}"
                            if base_desc
                            else f"**Categoria:** {category.capitalize()}"
                        )
                    else:
                        sub_desc = base_desc
                    sub_start = subtask.get("start_date") or start_date
                    sub_due = subtask.get("due_date") or due_date
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
                        "issue[start_date]": sub_start,
                        "issue[due_date]": sub_due,
                        "issue[estimated_hours]": str(sub_hours),
                        "issue[custom_field_values][5]": user_id,
                        "issue[custom_field_values][10]": "12 - Implementação de Nova Funcionalidade do Tipo Interface de Usuário (backend e frontend)",
                        "issue[custom_field_values][2]": "JAVA",
                        "issue[custom_field_values][4]": "ordem verbal",
                        "issue[custom_field_values][7]": "0",
                        "issue[custom_field_values][8]": "0",
                        "issue[watcher_user_ids][]": "",
                        "commit": "Criar"
                    }
                    sub_payload.update(
                        _custom_fields_payload(
                            sistema, orgao_solicitante, atribuicao_catalogo, projeto_vinculado, notas
                        )
                    )

                    checklists = subtask.get("checklists", [])
                    for i, chk in enumerate(checklists):
                        sub_payload[f"issue[checklists_attributes][{i}][is_done]"] = "0"
                        sub_payload[f"issue[checklists_attributes][{i}][subject]"] = str(chk)
                        sub_payload[f"issue[checklists_attributes][{i}][_destroy]"] = "false"
                        sub_payload[f"issue[checklists_attributes][{i}][position]"] = str(i)
                        sub_payload[f"issue[checklists_attributes][{i}][is_section]"] = "false"
                        sub_payload[f"issue[checklists_attributes][{i}][id]"] = ""

                    r_sub = session.post(url_post, data=sub_payload, allow_redirects=True)

                    if r_sub.status_code == 200 and "/issues/" in r_sub.url and "new" not in r_sub.url:
                        sub_id = r_sub.url.split("?")[0].split("/")[-1]
                        print(f"[{_timestamp()}]  -> [OK] Subtarefa '{sub_title}' criada! ID: {sub_id} ({sub_hours}h)")
                    else:
                        # CORREÇÃO 3: Mostrar o erro real das Subtarefas
                        soup_sub_erro = BeautifulSoup(r_sub.text, "html.parser")
                        sub_err_div = soup_sub_erro.find("div", id="errorExplanation")
                        if sub_err_div:
                            texto_erro_sub = sub_err_div.get_text(separator=' | ', strip=True)
                            print(f"[{_timestamp()}]  -> [FALHA] {texto_erro_sub}")
                        else:
                            print(
                                f"[{_timestamp()}]  -> [FALHA] HTTP Status: {r_sub.status_code} | HTML: {r_sub.text[:100].strip()}")

                except Exception as ex_sub:
                    print(f"[{_timestamp()}]  -> [ERRO] Falha interna na subtarefa '{sub_title}': {ex_sub}")

        print(f"\n[{_timestamp()}] PROCESSO DE SPRINT CONCLUÍDO!")

    except PermissionError as pe:
        print(f"[{_timestamp()}] {pe}")
    except Exception as e:
        print(f"[{_timestamp()}] ERRO CRÍTICO no processo principal: {e}")


def get_redmine_subtasks(session, parent_id):
    print(f"\n[{_timestamp()}] Buscando subtarefas para o Pai #{parent_id}...")
    try:
        url_parent = f"{BASE_URL}/issues/{parent_id}"
        r = session.get(url_parent, timeout=60)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        subtasks = []

        for tr in soup.select("#issue_tree tr.issue"):
            classes = tr.get("class", [])
            issue_class = next((c for c in classes if c.startswith("issue-") and len(c) > 6), None)

            if issue_class:
                clean_id = issue_class.replace("issue-", "")
                subject_td = tr.select_one("td.subject")

                if subject_td:
                    full_text = subject_td.get_text(strip=True)
                    title = full_text.split(":", 1)[1].strip() if ":" in full_text else full_text
                else:
                    title = f"Subtarefa {clean_id}"

                subtasks.append({"id": clean_id, "title": title})

        print(f"[{_timestamp()}] {len(subtasks)} subtarefas encontradas.")
        return subtasks

    except Exception as e:
        print(f"[{_timestamp()}] ERRO ao buscar subtarefas: {e}")
        return []


def close_single_subtask(session, sub_id, files_list, notas=""):
    import urllib.parse
    import mimetypes
    import re

    print(f"\n[{_timestamp()}] ===============================================")
    print(f"[{_timestamp()}] INICIANDO FECHAMENTO COMPLETO: Subtarefa #{sub_id}")

    try:
        url_sub = f"{BASE_URL}/issues/{sub_id}"
        r_sub = session.get(url_sub, timeout=60)
        soup_sub = BeautifulSoup(r_sub.text, "html.parser")

        csrf_meta = soup_sub.find("meta", attrs={"name": "csrf-token"})
        if not csrf_meta:
            print(f"[{_timestamp()}] ERRO CRÍTICO: Token CSRF não localizado.")
            return
        csrf_token_val = csrf_meta.get("content")

        lock_input = soup_sub.find("input", attrs={"name": "issue[lock_version]"})
        lock_version_val = lock_input.get("value") if lock_input else "0"

        uploaded_tokens = []
        if files_list:
            for index, file_info in enumerate(files_list, start=1):
                file_path = file_info["path"]
                file_name = file_info["name"]

                mime_type, _ = mimetypes.guess_type(file_path)
                mime_type = mime_type or "application/octet-stream"

                encoded_name = urllib.parse.quote(file_name)
                encoded_mime = urllib.parse.quote(mime_type)

                with open(file_path, "rb") as f:
                    file_data = f.read()

                upload_url = f"{BASE_URL}/uploads.js?attachment_id={index}&filename={encoded_name}&content_type={encoded_mime}"
                headers = {
                    "Content-Type": "application/octet-stream",
                    "Accept": "*/*",
                    "X-CSRF-Token": csrf_token_val,
                    "X-Requested-With": "XMLHttpRequest"
                }
                r_up = session.post(upload_url, data=file_data, headers=headers)

                if r_up.status_code == 200:
                    match = re.search(r"val\(['\"]([a-zA-Z0-9\.\-_]+)['\"]\)", r_up.text)
                    if match:
                        uploaded_tokens.append({"name": file_name, "token": match.group(1)})
                        print(f"[{_timestamp()}] Upload efetuado: {file_name}")

        form = soup_sub.find("form", id="issue-form")
        payload_list = []

        ignorar_nomes = [
            "utf8", "_method", "authenticity_token", "form_update_triggered_by",
            "issue[status_id]", "time_entry[hours]", "time_entry[activity_id]",
            "commit", "issue[lock_version]", "time_entry[comments]", "issue[notes]",
        ]

        for elem in form.find_all(["input", "select", "textarea"]):
            name = elem.get("name")
            if not name or name in ignorar_nomes or "checklists_attributes" in name:
                continue

            elem_type = elem.get("type", "").lower() if elem.name == "input" else ""
            if elem_type in ["submit", "button", "file", "image"]:
                continue
            if elem_type in ["checkbox", "radio"] and not elem.has_attr("checked"):
                continue

            val = ""
            if elem.name == "textarea":
                val = elem.text
            elif elem.name == "select":
                selected = elem.find("option", selected=True)
                val = selected.get("value", "") if selected else (
                    elem.find("option").get("value", "") if elem.find("option") else "")
            else:
                val = elem.get("value", "")

            payload_list.append((name, val))

        est_hours_val = "0"
        est_div = soup_sub.select_one(".estimated-hours .value")
        if est_div:
            est_hours_val = est_div.get_text(strip=True).replace("h", "").strip()
        else:
            est_input = soup_sub.find("input", attrs={"name": "issue[estimated_hours]"})
            if est_input and est_input.get("value"):
                est_hours_val = est_input.get("value")

        hours_cleaned = est_hours_val.replace(",", ".")
        if hours_cleaned.endswith(".00"):
            hours_cleaned = hours_cleaned[:-3]
        if not hours_cleaned:
            hours_cleaned = "0"

        payload_list.extend([
            ("utf8", "✓"),
            ("_method", "patch"),
            ("authenticity_token", csrf_token_val),
            ("form_update_triggered_by", ""),
            ("issue[status_id]", "5"),
            ("time_entry[hours]", hours_cleaned),
            ("time_entry[activity_id]", "9"),
            ("time_entry[comments]", ""),
            ("issue[lock_version]", lock_version_val),
        ])

        chk_id_inputs = form.find_all("input",
                                      attrs={"name": re.compile(r"issue\[checklists_attributes\]\[\d+\]\[id\]")})

        for idx, chk_input in enumerate(chk_id_inputs):
            chk_id = chk_input.get("value")
            if chk_id:
                subject_input = form.find("input", attrs={"name": f"issue[checklists_attributes][{idx}][subject]"})
                subject_val = subject_input.get("value", "") if subject_input else ""

                payload_list.extend([
                    (f"issue[checklists_attributes][{idx}][is_done]", "0"),
                    (f"issue[checklists_attributes][{idx}][is_done]", "1"),
                    (f"issue[checklists_attributes][{idx}][subject]", subject_val),
                    (f"issue[checklists_attributes][{idx}][_destroy]", "false"),
                    (f"issue[checklists_attributes][{idx}][position]", str(idx)),
                    (f"issue[checklists_attributes][{idx}][is_section]", "false"),
                    (f"issue[checklists_attributes][{idx}][id]", str(chk_id))
                ])

        if uploaded_tokens:
            for i, token_data in enumerate(uploaded_tokens, start=1):
                payload_list.extend([
                    (f"attachments[{i}][filename]", token_data["name"]),
                    (f"attachments[{i}][description]", ""),
                    (f"attachments[{i}][token]", token_data["token"])
                ])

        payload_list.append(("attachments[dummy][file]", ""))
        if notas.strip():
            payload_list.append(("issue[notes]", notas.strip()))
        payload_list.append(("commit", "Enviar"))

        update_url = f"{BASE_URL}/issues/{sub_id}"
        r_update = session.post(update_url, data=payload_list, allow_redirects=True)

        if r_update.history:
            print(
                f"[{_timestamp()}] -> [SUCESSO] Subtarefa #{sub_id} Finalizada com Checklists e {hours_cleaned}h apontadas!")
        else:
            soup_erro = BeautifulSoup(r_update.text, "html.parser")
            err_div = soup_erro.find("div", id="errorExplanation")
            if err_div:
                texto_erro = err_div.get_text(separator=' | ', strip=True)
                print(f"[{_timestamp()}] -> [FALHA DE VALIDAÇÃO]: {texto_erro}")
            else:
                print(f"[{_timestamp()}] -> [FALHA] Atualização recusada silenciosamente pelo servidor.")

    except Exception as e:
        print(f"[{_timestamp()}] ERRO CRÍTICO no barramento de execução: {e}")
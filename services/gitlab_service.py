import os
import requests
import datetime
from dotenv import load_dotenv

# Carrega as variáveis do arquivo .env
load_dotenv()

# ==========================================
# CONFIGURAÇÕES DO GITLAB
# ==========================================
GITLAB_BASE_URL = "https://gitlab.ssp.go.gov.br/api/v4"
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN")

# Se deixar vazio [], o script descobre automaticamente todos os projetos editados no dia.
# Se quiser forçar projetos específicos, coloque os IDs numéricos: [123, 456]
PROJECT_IDS = []


def _get_headers():
    if not GITLAB_TOKEN:
        raise ValueError("GITLAB_TOKEN não encontrado no arquivo .env! Verifique suas configurações.")
    return {"PRIVATE-TOKEN": GITLAB_TOKEN}


def _get_gitlab_user_id(username: str) -> int:
    """Busca o ID numérico do usuário no GitLab a partir do seu username."""
    url = f"{GITLAB_BASE_URL}/users"
    r = requests.get(url, headers=_get_headers(), params={"username": username})
    r.raise_for_status()
    users = r.json()
    if not users:
        raise ValueError(f"Usuário '{username}' não encontrado no GitLab.")
    return users[0]['id']


def _get_project_name(project_id: int) -> str:
    """
    Faz uma chamada rápida à API de Projetos do GitLab para pegar o nome legível.
    """
    url = f"{GITLAB_BASE_URL}/projects/{project_id}"
    r = requests.get(url, headers=_get_headers())

    if r.status_code == 200:
        return r.json().get('name_with_namespace', f"Projeto ID {project_id}")
    else:
        print(f"[API ALERTA] Falha ao buscar nome do projeto {project_id}: HTTP {r.status_code} - {r.text}")
        return f"Projeto ID {project_id}"


def fetch_active_projects(username: str, start_date_str: str, end_date_str: str) -> list:
    """
    Varre os eventos de push do usuário no intervalo selecionado,
    descobre os IDs e busca os nomes reais de cada projeto.
    """
    try:
        user_id = _get_gitlab_user_id(username)

        start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()

        after_date = start_date.strftime("%Y-%m-%d")
        before_date = (end_date + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

        url = f"{GITLAB_BASE_URL}/users/{user_id}/events"
        params = {
            "action": "pushed",
            "after": after_date,
            "before": before_date,
            "per_page": 100
        }

        r = requests.get(url, headers=_get_headers(), params=params)
        r.raise_for_status()
        events = r.json()

        unique_project_ids = set()
        for event in events:
            unique_project_ids.add(event['project_id'])

        projects_data = []
        for p_id in unique_project_ids:
            p_name = _get_project_name(p_id)
            projects_data.append({"id": p_id, "name": p_name})

        return projects_data

    except Exception as e:
        print(f"[GITLAB ERROR] Falha ao buscar projetos: {e}")
        raise e


def extract_project_diff_for_day(author: str, target_date_str: str, project_ids: list) -> str | None:
    """
    Gera o diff acumulado de commits criados pelo autor em uma data específica,
    restringindo a pesquisa exclusivamente ao subconjunto de IDs informados.
    """
    try:
        target_date = datetime.datetime.strptime(target_date_str, "%Y-%m-%d").date()
        since_date = target_date.strftime("%Y-%m-%dT00:00:00Z")
        until_date = target_date.strftime("%Y-%m-%dT23:59:59Z")

        combined_diff = f"=== Relatório de Diffs: {author} em {target_date_str} ===\n"
        combined_diff += f"Projetos analisados: {len(project_ids)}\n\n"

        total_commits_found = 0

        for p_id in project_ids:
            commits_url = f"{GITLAB_BASE_URL}/projects/{p_id}/repository/commits"
            params = {
                "author": author,
                "since": since_date,
                "until": until_date,
                "all": "true",
                "per_page": 100
            }

            r_commits = requests.get(commits_url, headers=_get_headers(), params=params)
            if r_commits.status_code != 200:
                continue

            commits = r_commits.json()
            if not commits:
                continue

            total_commits_found += len(commits)

            combined_diff += f"\n{'=' * 60}\n"
            combined_diff += f"PROJETO ID: {p_id}\n"
            combined_diff += f"{'=' * 60}\n\n"

            for commit in commits:
                commit_id = commit['id']
                commit_msg = commit['title']

                combined_diff += f"[{commit_id[:8]}] {commit_msg}\n"
                combined_diff += "-" * 50 + "\n"

                diff_url = f"{GITLAB_BASE_URL}/projects/{p_id}/repository/commits/{commit_id}/diff"
                r_diff = requests.get(diff_url, headers=_get_headers())

                if r_diff.status_code == 200:
                    diffs = r_diff.json()
                    for file_diff in diffs:
                        combined_diff += f"Arquivo: {file_diff.get('new_path')}\n"
                        combined_diff += f"{file_diff.get('diff')}\n"
                else:
                    combined_diff += "(Erro ao carregar diff de alterações deste commit)\n"

                combined_diff += "\n" + ("-" * 50) + "\n\n"

        if total_commits_found == 0:
            return None

        return combined_diff

    except Exception as e:
        return f"Erro crítico na extração de diffs: {str(e)}"
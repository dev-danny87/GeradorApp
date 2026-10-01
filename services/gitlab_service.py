import requests
import datetime

from utils.app_config import get_config

# ==========================================
# CONFIGURAÇÕES DO GITLAB
# ==========================================
GITLAB_BASE_URL = "https://gitlab.ssp.go.gov.br/api/v4"


def _get_headers():
    token = get_config("GITLAB_TOKEN")
    if not token:
        raise ValueError(
            "GITLAB_TOKEN não encontrado no .env nem em ~/ge.txt! Verifique suas configurações."
        )
    return {"PRIVATE-TOKEN": token}


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
    Retorna [{"id": int, "name": str}, ...].
    """
    try:
        user_id = _get_gitlab_user_id(username)

        start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()

        after_date = start_date.strftime("%Y-%m-%d")
        before_date = (end_date + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

        unique_project_ids = set()
        page = 1

        while True:
            url = f"{GITLAB_BASE_URL}/users/{user_id}/events"
            params = {
                "action": "pushed",
                "after": after_date,
                "before": before_date,
                "per_page": 100,
                "page": page,
            }

            r = requests.get(url, headers=_get_headers(), params=params)
            r.raise_for_status()
            events = r.json()

            if not events:
                break

            for event in events:
                project_id = event.get("project_id")
                if project_id is not None:
                    unique_project_ids.add(project_id)

            total_pages = int(r.headers.get("X-Total-Pages", 1))
            if page >= total_pages:
                break
            page += 1

        projects_data = []
        for p_id in sorted(unique_project_ids):
            p_name = _get_project_name(p_id)
            projects_data.append({"id": p_id, "name": p_name})

        return projects_data

    except Exception as e:
        print(f"[GITLAB ERROR] Falha ao buscar projetos: {e}")
        raise e


def _get_project_web_url(project_id: int) -> str | None:
    """Return the GitLab web URL for a project, used as fallback for commit links."""
    url = f"{GITLAB_BASE_URL}/projects/{project_id}"
    r = requests.get(url, headers=_get_headers())
    if r.status_code == 200:
        return r.json().get("web_url")
    return None


def _gitlab_commit_web_url(commit: dict, project_id: int, project_web_url: str | None) -> str:
    web_url = commit.get("web_url")
    if web_url:
        return web_url
    commit_id = commit.get("id", "")
    if project_web_url and commit_id:
        return f"{project_web_url.rstrip('/')}/-/commit/{commit_id}"
    return ""


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

            project_web_url = _get_project_web_url(p_id)

            for commit in commits:
                commit_id = commit['id']
                commit_msg = commit['title']
                commit_url = _gitlab_commit_web_url(commit, p_id, project_web_url)

                if commit_url:
                    combined_diff += f"COMMIT_URL: {commit_url}\n"
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

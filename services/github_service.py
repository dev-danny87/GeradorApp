import os
import requests
import datetime
from dotenv import load_dotenv

load_dotenv()

GITHUB_BASE_URL = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")


def _get_headers():
    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN não encontrado no arquivo .env! Verifique suas configurações.")
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def fetch_accessible_repositories() -> list:
    """
    Lista repositórios GitHub acessíveis ao token.
    Retorna [{"id": int, "name": str, "full_name": str}, ...].
    """
    repos_data = []
    page = 1

    while True:
        url = f"{GITHUB_BASE_URL}/user/repos"
        params = {
            "affiliation": "owner,collaborator,organization_member",
            "per_page": 100,
            "page": page,
            "sort": "full_name",
            "direction": "asc",
        }
        r = requests.get(url, headers=_get_headers(), params=params)
        r.raise_for_status()
        repos = r.json()

        if not repos:
            break

        for repo in repos:
            repos_data.append({
                "id": repo["id"],
                "name": repo.get("full_name", repo.get("name", f"Repo ID {repo['id']}")),
                "full_name": repo.get("full_name", ""),
            })

        link_header = r.headers.get("Link", "")
        if 'rel="next"' not in link_header:
            break
        page += 1

    return repos_data


def extract_repo_diff_for_day(author: str, target_date_str: str, repo_full_name: str) -> str | None:
    """
    Gera o diff acumulado de commits criados pelo autor em uma data específica
    para um repositório GitHub (owner/repo).
    """
    try:
        target_date = datetime.datetime.strptime(target_date_str, "%Y-%m-%d").date()
        since_date = target_date.strftime("%Y-%m-%dT00:00:00Z")
        until_date = target_date.strftime("%Y-%m-%dT23:59:59Z")

        combined_diff = f"=== Relatório de Diffs: {author} em {target_date_str} ===\n"
        combined_diff += f"Repositório analisado: {repo_full_name}\n\n"

        commits_url = f"{GITHUB_BASE_URL}/repos/{repo_full_name}/commits"
        params = {
            "author": author,
            "since": since_date,
            "until": until_date,
            "per_page": 100,
        }

        r_commits = requests.get(commits_url, headers=_get_headers(), params=params)
        if r_commits.status_code != 200:
            return None

        commits = r_commits.json()
        if not commits:
            return None

        total_commits_found = len(commits)

        combined_diff += f"\n{'=' * 60}\n"
        combined_diff += f"REPOSITÓRIO: {repo_full_name}\n"
        combined_diff += f"{'=' * 60}\n\n"

        for commit in commits:
            commit_sha = commit["sha"]
            commit_msg = commit["commit"]["message"].split("\n")[0]

            combined_diff += f"[{commit_sha[:8]}] {commit_msg}\n"
            combined_diff += "-" * 50 + "\n"

            detail_url = f"{GITHUB_BASE_URL}/repos/{repo_full_name}/commits/{commit_sha}"
            r_detail = requests.get(detail_url, headers=_get_headers())

            if r_detail.status_code == 200:
                detail = r_detail.json()
                for file_diff in detail.get("files", []):
                    combined_diff += f"Arquivo: {file_diff.get('filename')}\n"
                    patch = file_diff.get("patch")
                    if patch:
                        combined_diff += f"{patch}\n"
                    else:
                        combined_diff += "(Arquivo binário ou sem patch disponível)\n"
            else:
                combined_diff += "(Erro ao carregar diff de alterações deste commit)\n"

            combined_diff += "\n" + ("-" * 50) + "\n\n"

        if total_commits_found == 0:
            return None

        return combined_diff

    except Exception as e:
        return f"Erro crítico na extração de diffs: {str(e)}"

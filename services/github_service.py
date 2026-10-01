import requests
import datetime

from utils.app_config import get_config

GITHUB_BASE_URL = "https://api.github.com"


def _get_headers():
    token = get_config("GITHUB_TOKEN")
    if not token:
        raise ValueError(
            "GITHUB_TOKEN não encontrado no .env nem em ~/ge.txt! Verifique suas configurações."
        )
    return {
        "Authorization": f"Bearer {token}",
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


def fetch_active_repositories(username: str, start_date_str: str, end_date_str: str) -> list:
    """
    Descobre repositórios com PushEvent do usuário no intervalo selecionado.
    Retorna [{"id": int|None, "name": str, "full_name": str}, ...].
    """
    start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
    start_dt = datetime.datetime.combine(start_date, datetime.time.min).replace(tzinfo=datetime.timezone.utc)
    end_dt = datetime.datetime.combine(end_date, datetime.time.max).replace(tzinfo=datetime.timezone.utc)

    repos_by_name = {}
    page = 1

    while True:
        url = f"{GITHUB_BASE_URL}/users/{username}/events"
        params = {"per_page": 100, "page": page}
        r = requests.get(url, headers=_get_headers(), params=params)
        r.raise_for_status()
        events = r.json()

        if not events:
            break

        reached_before_range = False
        for event in events:
            created_at = event.get("created_at")
            if not created_at:
                continue

            event_dt = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if event_dt < start_dt:
                reached_before_range = True
                continue
            if event_dt > end_dt:
                continue
            if event.get("type") != "PushEvent":
                continue

            repo = event.get("repo") or {}
            full_name = repo.get("name") or ""
            if not full_name:
                continue

            repos_by_name[full_name] = {
                "id": repo.get("id"),
                "name": full_name,
                "full_name": full_name,
            }

        link_header = r.headers.get("Link", "")
        if reached_before_range or 'rel="next"' not in link_header:
            break
        page += 1

    if repos_by_name:
        return [repos_by_name[key] for key in sorted(repos_by_name.keys())]

    # Fallback: scan accessible repos for commits by author in the date range
    since_date = start_date.strftime("%Y-%m-%dT00:00:00Z")
    until_date = end_date.strftime("%Y-%m-%dT23:59:59Z")
    active = []

    for repo in fetch_accessible_repositories():
        full_name = repo.get("full_name") or ""
        if not full_name:
            continue

        commits_url = f"{GITHUB_BASE_URL}/repos/{full_name}/commits"
        params = {
            "author": username,
            "since": since_date,
            "until": until_date,
            "per_page": 1,
        }
        r_commits = requests.get(commits_url, headers=_get_headers(), params=params)
        if r_commits.status_code != 200:
            continue
        commits = r_commits.json()
        if commits:
            active.append(repo)

    return active


def extract_repo_diff_for_day(author: str, target_date_str: str, repo_full_name: str) -> str | None:
    """
    Gera o diff acumulado de commits criados pelo autor em uma data específica
    para um repositório GitHub (owner/repo).
    """
    return extract_repos_diff_for_day(author, target_date_str, [repo_full_name])


def extract_repos_diff_for_day(author: str, target_date_str: str, repo_full_names: list) -> str | None:
    """
    Gera o diff acumulado de commits do autor em uma data específica
    para um ou mais repositórios GitHub (owner/repo).
    """
    try:
        target_date = datetime.datetime.strptime(target_date_str, "%Y-%m-%d").date()
        since_date = target_date.strftime("%Y-%m-%dT00:00:00Z")
        until_date = target_date.strftime("%Y-%m-%dT23:59:59Z")

        combined_diff = f"=== Relatório de Diffs: {author} em {target_date_str} ===\n"
        combined_diff += f"Repositórios analisados: {len(repo_full_names)}\n\n"

        total_commits_found = 0

        for repo_full_name in repo_full_names:
            commits_url = f"{GITHUB_BASE_URL}/repos/{repo_full_name}/commits"
            params = {
                "author": author,
                "since": since_date,
                "until": until_date,
                "per_page": 100,
            }

            r_commits = requests.get(commits_url, headers=_get_headers(), params=params)
            if r_commits.status_code != 200:
                continue

            commits = r_commits.json()
            if not commits:
                continue

            total_commits_found += len(commits)

            combined_diff += f"\n{'=' * 60}\n"
            combined_diff += f"REPOSITÓRIO: {repo_full_name}\n"
            combined_diff += f"{'=' * 60}\n\n"

            for commit in commits:
                commit_sha = commit["sha"]
                commit_msg = commit["commit"]["message"].split("\n")[0]
                commit_url = commit.get("html_url") or ""

                if commit_url:
                    combined_diff += f"COMMIT_URL: {commit_url}\n"
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

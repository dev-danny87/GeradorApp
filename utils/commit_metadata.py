"""
Parse commit URLs from exported diff text and attach them to AI tasks as metadata.

Commit links are kept out of Redmine descriptions; they flow into fechamento notas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

COMMIT_URL_PREFIX = "COMMIT_URL:"
ARQUIVO_PREFIX = "Arquivo:"
COMMIT_HEADER_RE = re.compile(r"^\[([0-9a-fA-F]{7,40})\]\s*(.*)$")
URL_IN_TEXT_RE = re.compile(r"https?://[^\s\)\]>]+")
SECTION_HEADER_RE = re.compile(r"^\*\*([^*]+):\*\*\s*$")


@dataclass
class ParsedCommit:
    url: str
    files: list[str] = field(default_factory=list)
    message: str = ""
    short_sha: str = ""


def _normalize_path(path: str) -> str:
    cleaned = (path or "").strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.lstrip("/")


def _paths_overlap(task_file: str, commit_file: str) -> bool:
    task_norm = _normalize_path(task_file)
    commit_norm = _normalize_path(commit_file)
    if not task_norm or not commit_norm:
        return False
    if task_norm == commit_norm:
        return True
    if task_norm.endswith("/" + commit_norm) or commit_norm.endswith("/" + task_norm):
        return True
    return task_norm.split("/")[-1] == commit_norm.split("/")[-1]


def parse_commits_from_diff(text: str) -> list[ParsedCommit]:
    """Extract commit URLs, messages and changed files from exported diff text."""
    if not text:
        return []

    commits: list[ParsedCommit] = []
    current: ParsedCommit | None = None
    in_commit_body = False

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if line.startswith(COMMIT_URL_PREFIX):
            url = line[len(COMMIT_URL_PREFIX):].strip()
            if url:
                current = ParsedCommit(url=url)
                commits.append(current)
                in_commit_body = True
            continue

        if current is None:
            continue

        if line.startswith(ARQUIVO_PREFIX):
            file_path = line[len(ARQUIVO_PREFIX):].strip()
            if file_path:
                current.files.append(file_path)
            in_commit_body = True
            continue

        header_match = COMMIT_HEADER_RE.match(line)
        if header_match:
            current.short_sha = header_match.group(1)
            current.message = (header_match.group(2) or "").strip()
            in_commit_body = True
            continue

        if in_commit_body and line.startswith("=" * 20):
            current = None
            in_commit_body = False
            continue

        if in_commit_body and re.fullmatch(r"-{10,}", line):
            continue

    return [c for c in commits if c.url]


def build_commits_index(diff_texts: list[str]) -> dict[str, ParsedCommit]:
    """Map commit URL -> ParsedCommit across multiple diff files."""
    index: dict[str, ParsedCommit] = {}
    for text in diff_texts:
        for commit in parse_commits_from_diff(text):
            existing = index.get(commit.url)
            if not existing:
                index[commit.url] = commit
                continue
            if commit.message and not existing.message:
                existing.message = commit.message
            if commit.short_sha and not existing.short_sha:
                existing.short_sha = commit.short_sha
            for path in commit.files:
                if path not in existing.files:
                    existing.files.append(path)
    return index


def attach_commit_links_to_tasks(tasks: list[dict], diff_text: str) -> list[dict]:
    """Match tasks to commits by affected_files overlap and set commit_links metadata."""
    commits = parse_commits_from_diff(diff_text)
    if not commits:
        for task in tasks:
            task.setdefault("commit_links", [])
        return tasks

    for task in tasks:
        affected = task.get("affected_files") or []
        links: set[str] = set(task.get("commit_links") or [])

        for commit in commits:
            if not affected:
                continue
            if any(
                _paths_overlap(task_file, commit_file)
                for task_file in affected
                for commit_file in commit.files
            ):
                links.add(commit.url)

        task["commit_links"] = sorted(links)

    return tasks


def enrich_tasks_commit_links_from_diffs(tasks: list[dict], diff_texts: list[str]) -> list[dict]:
    """Attach commit links from multiple diff files (for fallback enrichment)."""
    for diff_text in diff_texts:
        attach_commit_links_to_tasks(tasks, diff_text)
    return tasks


def format_commit_notas(links: list[str]) -> str:
    """Format commit URLs as fechamento notas evidence text (short form)."""
    unique = sorted({link.strip() for link in links if link and link.strip()})
    if not unique:
        return ""
    lines = ["Evidências (commits):"]
    lines.extend(f"- {url}" for url in unique)
    return "\n".join(lines)


def _extract_description_sections(description: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_key = "_preamble"
    current_lines: list[str] = []

    def flush():
        text = "\n".join(current_lines).strip()
        if text:
            sections[current_key] = text

    for line in (description or "").split("\n"):
        match = SECTION_HEADER_RE.match(line.strip())
        if match:
            flush()
            current_key = match.group(1).strip().lower()
            current_lines = []
        else:
            current_lines.append(line)
    flush()
    return sections


def _section_text(sections: dict[str, str], *keys: str) -> str:
    for key in keys:
        key_l = key.lower()
        for section_key, value in sections.items():
            if key_l in section_key:
                return value
    return ""


def build_detailed_fechamento_notas(
        task: dict,
        commits_index: dict[str, ParsedCommit] | None = None,
) -> str:
    """Build rich closing notes from task metadata and commit evidence."""
    title = (task.get("task_title") or task.get("title") or "Tarefa técnica").strip()
    category = (task.get("category") or "").strip()
    hours = task.get("estimated_hours", "")
    description = (task.get("description") or "").strip()
    affected = [str(p).strip() for p in (task.get("affected_files") or []) if str(p).strip()]
    links = [
        str(url).strip()
        for url in (task.get("commit_links") or [])
        if str(url).strip()
    ]
    links = sorted(set(links))
    commits_index = commits_index or {}

    sections = _extract_description_sections(description)
    contexto = _section_text(sections, "contexto")
    detalhes = _section_text(sections, "detalhes técnicos", "detalhes tecnicos", "detalhes")
    impacto = _section_text(sections, "impacto", "comportamento esperado")

    lines: list[str] = [
        "## Resumo",
        title,
    ]
    meta_bits = []
    if category:
        meta_bits.append(f"Categoria: {category}")
    if hours != "" and hours is not None:
        meta_bits.append(f"Estimativa: {hours}h")
    if meta_bits:
        lines.append(" | ".join(meta_bits))

    lines.append("")
    lines.append("## Trabalho realizado")
    if contexto:
        lines.append("### Contexto")
        lines.append(contexto)
        lines.append("")
    if detalhes:
        lines.append("### Detalhes técnicos")
        lines.append(detalhes)
        lines.append("")
    if impacto:
        lines.append("### Impacto / comportamento esperado")
        lines.append(impacto)
        lines.append("")
    if not (contexto or detalhes or impacto) and description:
        lines.append(description)
        lines.append("")

    if affected:
        lines.append("## Arquivos alterados")
        lines.extend(f"- {path}" for path in affected)
        lines.append("")

    lines.append("## Evidências (commits)")
    if links:
        for url in links:
            commit = commits_index.get(url)
            if commit and (commit.message or commit.short_sha):
                sha = commit.short_sha or ""
                msg = commit.message or ""
                label = f"[{sha}] {msg}".strip() if sha else msg
                lines.append(f"- {url}")
                if label:
                    lines.append(f"  {label}")
            else:
                lines.append(f"- {url}")
    else:
        lines.append("- Nenhuma URL de commit associada automaticamente a esta tarefa.")
    lines.append("")

    lines.append("## Encerramento")
    lines.append(
        "Implementação concluída conforme o escopo descrito. "
        "Os commits listados acima constituem a evidência técnica do trabalho realizado."
    )
    return "\n".join(lines).strip()


def strip_urls_from_description(task: dict) -> dict:
    """Remove URL-like content from description if the model added commit links there."""
    description = task.get("description") or ""
    if not description or not URL_IN_TEXT_RE.search(description):
        return task

    cleaned_lines = []
    for line in description.split("\n"):
        if URL_IN_TEXT_RE.search(line):
            continue
        cleaned_lines.append(line)

    updated = dict(task)
    updated["description"] = "\n".join(cleaned_lines).strip()
    return updated

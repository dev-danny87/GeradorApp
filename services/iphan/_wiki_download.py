import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from services.iphan._common import (
    download_file,
    is_app_running,
    safe_dirname,
    safe_filename,
    safe_mkdir,
    timestamp,
)
from services.iphan._error_registry import record_error
from services.iphan._wiki_backlog import (
    BacklogRow,
    resolve_wiki_assets,
    wiki_slug_from_url,
)


def _issue_workers() -> int:
    try:
        count = int(os.getenv("THREADS", "1"))
    except ValueError:
        count = 1
    return max(1, min(count, 8))


def _assignee_dest(dirs: dict, assignee: str, wiki_slug: str) -> str:
    pdf_name = safe_filename(wiki_slug) + ".pdf"
    issue_dir = os.path.join(dirs["evidencias"], safe_dirname(assignee), safe_dirname(wiki_slug))
    return os.path.join(issue_dir, pdf_name)


def _copy_pdf(source: str, dest: str) -> None:
    safe_mkdir(os.path.dirname(dest))
    shutil.copy2(source, dest)


def _format_row_log(row: BacklogRow, *, developer_only: bool) -> str:
    if developer_only:
        return f"Sprint #{row.sprint_number} | {row.developer} | {row.title_text}"
    parts = [f"Sprint #{row.sprint_number}"]
    if row.analyst:
        parts.append(f"analista={row.analyst}")
    if row.developer:
        parts.append(f"desenvolvedor={row.developer}")
    parts.append(row.title_text)
    return " | ".join(parts)


def _row_context(row: BacklogRow, *, developer_only: bool) -> str:
    return _format_row_log(row, developer_only=developer_only)


def _download_wiki_row(
    session,
    row: BacklogRow,
    dirs: dict,
    assets_cache: dict,
    individual_copied: set[str],
    cache_lock: threading.Lock,
    individual_lock: threading.Lock,
    *,
    developer_only: bool = False,
) -> bool:
    assignees = row.assignees(developer_only=developer_only)

    with cache_lock:
        cached = assets_cache.get(row.wiki_url)
    if cached:
        pdf_url, slug = cached
    else:
        assets = resolve_wiki_assets(session, row.wiki_url)
        if not assets:
            print(f"[{timestamp()}] ERROR: não foi possível resolver PDF para {row.wiki_url}")
            record_error(
                kind="wiki_resolve",
                message="não foi possível resolver PDF",
                url=row.wiki_url,
                context=_row_context(row, developer_only=developer_only),
            )
            return False
        pdf_url, canonical_wiki_url = assets
        slug = wiki_slug_from_url(pdf_url) or wiki_slug_from_url(canonical_wiki_url)
        if not slug:
            print(f"[{timestamp()}] ERROR: não foi possível resolver slug para {row.wiki_url}")
            record_error(
                kind="wiki_resolve",
                message="não foi possível resolver slug",
                url=row.wiki_url,
                context=_row_context(row, developer_only=developer_only),
            )
            return False
        if slug != row.wiki_slug:
            print(f"[{timestamp()}] WARN: slug backlog {row.wiki_slug} -> canônico {slug}")
        with cache_lock:
            assets_cache[row.wiki_url] = (pdf_url, slug)

    pdf_name = safe_filename(slug) + ".pdf"
    primary_dest = _assignee_dest(dirs, assignees[0], slug)

    if not download_file(
        session,
        pdf_url,
        primary_dest,
        context=_row_context(row, developer_only=developer_only),
    ):
        return False

    if not os.path.isfile(primary_dest) or os.path.getsize(primary_dest) == 0:
        return False

    for assignee in assignees[1:]:
        dest = _assignee_dest(dirs, assignee, slug)
        _copy_pdf(primary_dest, dest)

    with individual_lock:
        if slug not in individual_copied:
            flat_dest = os.path.join(dirs["individual"], pdf_name)
            _copy_pdf(primary_dest, flat_dest)
            individual_copied.add(slug)

    print(f"[{timestamp()}] {_format_row_log(row, developer_only=developer_only)}")
    return True


def download_wiki_rows(
    session,
    rows: list[BacklogRow],
    dirs: dict,
    *,
    developer_only: bool = False,
) -> tuple[int, int]:
    if not rows:
        return 0, 0

    workers = _issue_workers()
    ok_count = 0
    fail_count = 0
    assets_cache: dict = {}
    individual_copied: set[str] = set()
    cache_lock = threading.Lock()
    individual_lock = threading.Lock()

    if workers == 1:
        for row in rows:
            if not is_app_running():
                break
            if _download_wiki_row(
                session,
                row,
                dirs,
                assets_cache,
                individual_copied,
                cache_lock,
                individual_lock,
                developer_only=developer_only,
            ):
                ok_count += 1
            else:
                fail_count += 1
        return ok_count, fail_count

    print(f"[{timestamp()}] Baixando {len(rows)} wiki PDF(s) com {workers} worker(s)")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _download_wiki_row,
                session,
                row,
                dirs,
                assets_cache,
                individual_copied,
                cache_lock,
                individual_lock,
                developer_only=developer_only,
            ): row
            for row in rows
        }
        for future in as_completed(futures):
            if not is_app_running():
                break
            try:
                if future.result():
                    ok_count += 1
                else:
                    fail_count += 1
            except Exception as exc:
                fail_count += 1
                print(f"[{timestamp()}] ERROR: falha ao baixar wiki PDF: {exc}")
                record_error(kind="download", message=str(exc), context="wiki PDF (thread)")

    return ok_count, fail_count

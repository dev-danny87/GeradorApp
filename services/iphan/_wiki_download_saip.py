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
from services.iphan._wiki_backlog import resolve_wiki_assets, wiki_slug_from_url
from services.iphan._wiki_sprints_saip import (
    SaipRow,
    SaipSprintBlock,
    SaipSprintPageData,
)


def _issue_workers() -> int:
    try:
        count = int(os.getenv("THREADS", "1"))
    except ValueError:
        count = 1
    return max(1, min(count, 8))


def row_pdf_basename(row: SaipRow, slug: str) -> str:
    if row.hu_number:
        return safe_filename(f"HU{row.hu_number}_{slug}")
    return safe_filename(slug)


def _assignee_dest(dirs: dict, sprint_slug: str, assignee: str, pdf_name: str) -> str:
    issue_dir = os.path.join(
        dirs["evidencias"],
        safe_dirname(sprint_slug),
        safe_dirname(assignee),
    )
    return os.path.join(issue_dir, pdf_name)


def _copy_pdf(source: str, dest: str) -> None:
    safe_mkdir(os.path.dirname(dest))
    shutil.copy2(source, dest)


def _format_row_log(row: SaipRow) -> str:
    parts = [f"{row.sprint_slug or f'Sprint #{row.sprint_number}'}"]
    if row.hu_number:
        parts.append(f"HU={row.hu_number}")
    if row.po:
        parts.append(f"po={row.po}")
    if row.analyst:
        parts.append(f"analista={row.analyst}")
    if row.developers:
        parts.append(f"desenvolvedor={', '.join(row.developers)}")
    parts.append(row.title_text)
    return " | ".join(parts)


def _log_shared_wiki_urls(rows: list[SaipRow]) -> None:
    url_to_hus: dict[str, list[str]] = {}
    for row in rows:
        if not row.wiki_url:
            continue
        url_to_hus.setdefault(row.wiki_url, []).append(row.hu_number or "?")

    for hus in url_to_hus.values():
        if len(hus) > 1:
            joined = " e HU ".join(hus)
            print(
                f"[{timestamp()}] WARN: HU {joined} compartilham a mesma wiki; "
                "gerando cópias com prefixo HU"
            )


def download_sprint_pdfs(session, sprints: list[SaipSprintBlock], dirs: dict) -> tuple[int, int]:
    ok_count = 0
    fail_count = 0

    for sprint in sprints:
        if not is_app_running():
            break
        if not sprint.sprint_slug or not sprint.sprint_wiki_url:
            print(
                f"[{timestamp()}] WARN: sprint #{sprint.sprint_number} sem slug/URL; "
                "PDF da sprint ignorado"
            )
            record_error(
                kind="other",
                message="sprint sem slug/URL; PDF da sprint ignorado",
                context=f"Sprint #{sprint.sprint_number}",
            )
            fail_count += 1
            continue

        sprint_dir = os.path.join(dirs["evidencias"], safe_dirname(sprint.sprint_slug))
        safe_mkdir(sprint_dir)

        assets = resolve_wiki_assets(session, sprint.sprint_wiki_url)
        if assets:
            pdf_url, _ = assets
        else:
            pdf_url = sprint.sprint_wiki_url.rstrip("/") + ".pdf"

        dest = os.path.join(sprint_dir, safe_filename(sprint.sprint_slug) + ".pdf")
        print(f"[{timestamp()}] Baixando sprint PDF: {sprint.sprint_slug}")
        if download_file(
            session,
            pdf_url,
            dest,
            context=f"Sprint PDF | {sprint.sprint_slug}",
        ):
            ok_count += 1
        else:
            fail_count += 1

    return ok_count, fail_count


def download_sprint_attachments(
    session,
    sprint: SaipSprintBlock,
    page_data: SaipSprintPageData,
    dirs: dict,
) -> tuple[int, int]:
    if not sprint.sprint_slug:
        return 0, 0

    attachments = page_data.attachments
    bulk_url = page_data.bulk_download_url
    if not attachments and not bulk_url:
        return 0, 0

    arquivos_dir = os.path.join(dirs["evidencias"], safe_dirname(sprint.sprint_slug), "arquivos")
    safe_mkdir(arquivos_dir)
    ok_count = 0
    fail_count = 0

    if attachments:
        print(
            f"[{timestamp()}] Baixando {len(attachments)} anexo(s) da sprint "
            f"{sprint.sprint_slug}..."
        )
        for attachment in attachments:
            if not is_app_running():
                break
            dest = os.path.join(arquivos_dir, safe_filename(attachment.filename))
            if download_file(
                session,
                attachment.download_url,
                dest,
                context=f"Anexo sprint | {sprint.sprint_slug} | {attachment.filename}",
            ):
                ok_count += 1
            else:
                fail_count += 1
    elif bulk_url:
        dest = os.path.join(
            arquivos_dir,
            safe_filename(f"{sprint.sprint_slug}_arquivos.zip"),
        )
        print(f"[{timestamp()}] Baixando anexos (zip) da sprint {sprint.sprint_slug}...")
        if download_file(
            session,
            bulk_url,
            dest,
            context=f"Anexos zip | {sprint.sprint_slug}",
        ):
            ok_count += 1
        else:
            fail_count += 1

    return ok_count, fail_count


def _download_saip_row(
    session,
    row: SaipRow,
    dirs: dict,
    assets_cache: dict,
    downloaded_by_url: dict[str, str],
    individual_copied: set[str],
    cache_lock: threading.Lock,
    individual_lock: threading.Lock,
    url_lock: threading.Lock,
) -> bool:
    assignees = row.assignees()
    sprint_slug = row.sprint_slug or f"Sprint-{row.sprint_number}"

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
                context=_format_row_log(row),
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
                context=_format_row_log(row),
            )
            return False
        if slug != row.wiki_slug:
            print(f"[{timestamp()}] WARN: slug {row.wiki_slug} -> canônico {slug}")
        with cache_lock:
            assets_cache[row.wiki_url] = (pdf_url, slug)

    pdf_basename = row_pdf_basename(row, slug)
    pdf_name = pdf_basename + ".pdf"
    primary_dest = _assignee_dest(dirs, sprint_slug, assignees[0], pdf_name)

    with url_lock:
        source_path = downloaded_by_url.get(row.wiki_url)

    if source_path and os.path.isfile(source_path) and os.path.getsize(source_path) > 0:
        _copy_pdf(source_path, primary_dest)
    else:
        if not download_file(session, pdf_url, primary_dest, context=_format_row_log(row)):
            return False
        if not os.path.isfile(primary_dest) or os.path.getsize(primary_dest) == 0:
            return False
        with url_lock:
            downloaded_by_url[row.wiki_url] = primary_dest

    for assignee in assignees[1:]:
        dest = _assignee_dest(dirs, sprint_slug, assignee, pdf_name)
        _copy_pdf(primary_dest, dest)

    with individual_lock:
        if pdf_name not in individual_copied:
            flat_dest = os.path.join(dirs["individual"], pdf_name)
            _copy_pdf(primary_dest, flat_dest)
            individual_copied.add(pdf_name)

    print(f"[{timestamp()}] {_format_row_log(row)}")
    return True


def download_saip_rows(session, rows: list[SaipRow], dirs: dict) -> tuple[int, int]:
    if not rows:
        return 0, 0

    _log_shared_wiki_urls(rows)

    workers = _issue_workers()
    ok_count = 0
    fail_count = 0
    assets_cache: dict = {}
    downloaded_by_url: dict[str, str] = {}
    individual_copied: set[str] = set()
    cache_lock = threading.Lock()
    individual_lock = threading.Lock()
    url_lock = threading.Lock()

    if workers == 1:
        for row in rows:
            if not is_app_running():
                break
            if _download_saip_row(
                session,
                row,
                dirs,
                assets_cache,
                downloaded_by_url,
                individual_copied,
                cache_lock,
                individual_lock,
                url_lock,
            ):
                ok_count += 1
            else:
                fail_count += 1
        return ok_count, fail_count

    print(f"[{timestamp()}] Baixando {len(rows)} wiki PDF(s) com {workers} worker(s)")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _download_saip_row,
                session,
                row,
                dirs,
                assets_cache,
                downloaded_by_url,
                individual_copied,
                cache_lock,
                individual_lock,
                url_lock,
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
                record_error(kind="download", message=str(exc), context="wiki PDF SAIP (thread)")

    return ok_count, fail_count

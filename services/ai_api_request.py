import os
import json
import requests
from typing import Callable, Optional
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
CLAUDE_API_KEY = os.getenv("CLAUDE_KEY")
CLAUDE_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
MAX_DIFF_CHARS = 150_000
MAX_GROUP_CHARS = 120_000
FILE_SEPARATOR_OVERHEAD = 80
MIN_DIFF_CHARS = 150

MODEL_CONFIGS = {
    "claude-sonnet-5": {
        "max_tokens": 65536,
        "thinking": {"type": "disabled"},
    },
    "claude-opus-4-8": {
        "max_tokens": 16384,
    },
    "claude-haiku-4-5-20251001": {
        "max_tokens": 32768,
    }
}

MAX_OUTPUT_TOKENS = {
    "claude-sonnet-5": 131072,
    "claude-opus-4-8": 131072,
    "claude-haiku-4-5-20251001": 65536,
}

MERGE_RESPONSE_SCHEMA = """{
  "merge_groups": [
    [0],
    [1, 3],
    [2]
  ]
}"""

RECONCILE_RESPONSE_SCHEMA = """{
  "hours": [0.0, 0.0, 0.0],
  "allocation_rationale_pt": "Breve explicação em português."
}"""

CHECKPOINT_FILENAME = "ai_tasks_checkpoint.json"

TASK_SCHEMA = """{
  "tasks": [
    {
      "task_title": "Título conciso da tarefa (ex: Refatoração do módulo de Autenticação)",
      "category": "Feature | Bugfix | Refactor | Test | Chore",
      "estimated_hours": 0.0,
      "description": "**Contexto:**\\nSua explicação aqui.\\n\\n**Detalhes Técnicos:**\\nSua explicação técnica aqui.\\n\\n**Impacto / Comportamento Esperado:**\\nImpacto aqui."
    }
  ]
}"""

DESCRIPTION_REQUIREMENTS = """The 'description' field MUST NOT be a single sentence. It must be a comprehensive, multi-paragraph string formatted in Markdown (using \\n for line breaks, ** for bolding, - for bullet points and escape those inner double quotes using a backslash (\")).
Every description MUST strictly follow this structure and include these exact headers:

**Contexto:**
(Explain what the code change represents from a business/system perspective. Why was this done?)

**Detalhes Técnicos:**
(Explain exactly what was modified in the code based on the diffs.)

**Impacto / Comportamento Esperado:**
(What does this change achieve? How does it affect the system or the end user?)"""

ProgressCallback = Callable[[int, int, str], None]


def _get_headers() -> dict:
    if not CLAUDE_API_KEY:
        raise ValueError("CLAUDE_KEY não encontrada no arquivo .env!")
    return {
        "x-api-key": CLAUDE_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json"
    }


def _truncate_diff(diff_content: str) -> str:
    if len(diff_content) <= MAX_DIFF_CHARS:
        return diff_content
    return diff_content[:MAX_DIFF_CHARS] + "\n\n...[TRUNCATED DUE TO LENGTH]..."


def _extract_json_from_response(raw_content: str) -> dict:
    raw_content = raw_content.strip()

    # Fallback cleanup in case any rogue markdown bypassed the prefill
    if "```json" in raw_content:
        raw_content = raw_content.split("```json")[-1].split("```")[0].strip()
    elif raw_content.startswith("```"):
        raw_content = raw_content.strip("`").strip()

    start = raw_content.find("{")
    end = raw_content.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw_content = raw_content[start:end + 1]

    parsed = json.loads(raw_content)
    if not isinstance(parsed, dict):
        raise ValueError("A resposta da API não é um objeto JSON válido.")
    return parsed


def _extract_text_from_message(payload: dict, prefilled: bool = True) -> str:
    for block in payload.get("content", []):
        if block.get("type") == "text" and "text" in block:
            text = block["text"]
            # Reattach the opening brace that we prefilled via the API
            return "{" + text if prefilled else text
    raise KeyError("No text block in API response content")


def _build_request_params(
        selected_model: str,
        system_prompt: str,
        user_content: str,
        max_tokens: int,
        prefill_json: bool = True
) -> dict:
    model_params = dict(MODEL_CONFIGS.get(selected_model, {"max_tokens": 4096}))
    model_params["max_tokens"] = max_tokens

    messages = [{"role": "user", "content": user_content}]

    # Assistant prefill trick to mathematically guarantee the AI outputs JSON
    # and ignores any urge to wrap it in markdown block quotes.
    if prefill_json:
        messages.append({"role": "assistant", "content": "{"})

    request_params = {
        "model": selected_model,
        "system": system_prompt,
        "messages": messages,
    }
    request_params.update(model_params)
    return request_params


def _repair_json_with_claude(broken_json: str, selected_model: str) -> dict:
    repair_prompt = (
        "You receive malformed JSON. Return ONLY corrected valid JSON with the same data and structure. "
        "Do not add markdown fences or commentary."
    )
    max_tokens = MODEL_CONFIGS.get(selected_model, {"max_tokens": 4096})["max_tokens"]
    request_params = _build_request_params(
        selected_model,
        repair_prompt,
        f"Fix this JSON:\n{broken_json}",
        max_tokens,
        prefill_json=True
    )

    response = requests.post(
        f"{CLAUDE_BASE_URL}/messages",
        headers=_get_headers(),
        json=request_params,
        timeout=300,
    )
    response.raise_for_status()
    payload = response.json()
    raw_text = _extract_text_from_message(payload, prefilled=True)
    return _extract_json_from_response(raw_text)


def _format_api_error(response: requests.Response) -> str:
    try:
        body = response.json()
        return body.get("error", {}).get("message") or response.text
    except Exception:
        return response.text or str(response.status_code)


def _serialize_tasks_json(tasks: list) -> str:
    return json.dumps({"tasks": tasks}, ensure_ascii=False, separators=(",", ":"))


def _save_group_checkpoint(
        output_dir: Optional[str],
        completed_groups: int,
        group_tasks: list[dict],
        last_group_label: str,
) -> None:
    if not output_dir:
        return
    checkpoint_path = os.path.join(output_dir, CHECKPOINT_FILENAME)
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "completed_groups": completed_groups,
                "group_tasks": group_tasks,
                "last_group_label": last_group_label,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"[API INFO] Checkpoint salvo: {checkpoint_path} (grupo {completed_groups})")


def _parse_message_response(payload: dict, selected_model: str) -> dict:
    stop_reason = payload.get("stop_reason")
    usage = payload.get("usage", {})
    output_tokens = usage.get("output_tokens", "?")
    print(f"[API INFO] stop_reason={stop_reason}, output_tokens={output_tokens}")

    if stop_reason == "max_tokens":
        raise ValueError(
            "Resposta truncada pelo limite de tokens (stop_reason=max_tokens). "
            "Tente reduzir o período de diffs ou use um modelo com maior capacidade."
        )

    raw_text = _extract_text_from_message(payload, prefilled=True)
    try:
        return _extract_json_from_response(raw_text)
    except json.JSONDecodeError as e:
        print(f"[API WARN] JSON inválido na resposta ({e}). Tentando reparo...")
        return _repair_json_with_claude(raw_text, selected_model)


def _call_claude_sync(
    system_prompt: str,
    user_content: str,
    selected_model: str,
    max_tokens_override: Optional[int] = None,
    timeout: int = 300,
) -> dict:
    base_max_tokens = max_tokens_override or MODEL_CONFIGS.get(selected_model, {"max_tokens": 4096})["max_tokens"]
    model_ceiling = MAX_OUTPUT_TOKENS.get(selected_model, 131072)
    token_limits = [base_max_tokens]
    if not max_tokens_override and base_max_tokens * 2 <= model_ceiling:
        token_limits.append(base_max_tokens * 2)

    last_error: Optional[Exception] = None

    for attempt, max_tokens in enumerate(token_limits):
        request_params = _build_request_params(
            selected_model, system_prompt, user_content, max_tokens, prefill_json=True
        )

        for json_attempt in range(2):
            try:
                response = requests.post(
                    f"{CLAUDE_BASE_URL}/messages",
                    headers=_get_headers(),
                    json=request_params,
                    timeout=timeout,
                )
                response.raise_for_status()
                payload = response.json()
                return _parse_message_response(payload, selected_model)
            except requests.exceptions.RequestException as e:
                error_text = _format_api_error(e.response) if e.response is not None else str(e)
                print(f"[API ERROR] Falha na comunicação com Messages API: {error_text}")
                raise ValueError(f"Messages API Error: {error_text}") from e
            except ValueError as e:
                last_error = e
                if "truncada pelo limite de tokens" in str(e) and attempt < len(token_limits) - 1:
                    print(
                        f"[API WARN] Tentando novamente com max_tokens={token_limits[attempt + 1]}..."
                    )
                    break
                raise
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                last_error = e
                if json_attempt == 0:
                    print("[API WARN] Resposta inválida, repetindo chamada...")
                    continue
                if attempt < len(token_limits) - 1:
                    print(
                        f"[API WARN] Tentando novamente com max_tokens={token_limits[attempt + 1]}..."
                    )
                    break
                raise ValueError(f"Resposta da API em formato inesperado: {e}") from e
        else:
            continue
        continue

    if last_error:
        raise last_error
    raise ValueError("Falha inesperada ao chamar a API.")


def _validate_tasks_payload(payload: dict, step_label: str) -> list:
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError(f"{step_label}: o JSON retornado não possui a lista 'tasks' esperada.")
    return tasks


def _is_empty_diff(content: str) -> bool:
    stripped = content.strip()
    if len(stripped) < MIN_DIFF_CHARS:
        return True
    if "Nenhum commit" in stripped and len(stripped) < 200:
        return True
    return False


def _file_entry_size(name: str, content: str) -> int:
    return len(_truncate_diff(content.strip())) + FILE_SEPARATOR_OVERHEAD + len(name)


def _estimate_group_size(items: list[tuple[str, str]]) -> int:
    return sum(_file_entry_size(name, content) for name, content in items)


def _group_diff_items_by_size(diff_items: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    non_empty: list[tuple[str, str]] = []
    for name, content in diff_items:
        if _is_empty_diff(content):
            print(f"[API INFO] Pulando diff vazio: {name}")
            continue
        non_empty.append((name, content))

    if not non_empty:
        return []

    groups: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    current_size = 0

    for name, content in non_empty:
        entry_size = _file_entry_size(name, content)

        if entry_size > MAX_GROUP_CHARS:
            if current:
                groups.append(current)
                current = []
                current_size = 0
            groups.append([(name, content)])
            continue

        if current and current_size + entry_size > MAX_GROUP_CHARS:
            groups.append(current)
            current = [(name, content)]
            current_size = entry_size
        else:
            current.append((name, content))
            current_size += entry_size

    if current:
        groups.append(current)
    return groups


def _format_group_diffs(group: list[tuple[str, str]]) -> str:
    parts = []
    for name, content in group:
        parts.append(f"--- FILE: {name} ---\n{_truncate_diff(content.strip())}")
    return "\n\n".join(parts)


def _group_label(group: list[tuple[str, str]]) -> str:
    if len(group) == 1:
        return group[0][0]
    names = ", ".join(name for name, _ in group[:3])
    if len(group) > 3:
        names += f" (+{len(group) - 3} mais)"
    return names


def _build_group_create_prompt() -> str:
    return f"""You are an expert Software Architect and Technical Project Manager. Your task is to analyze git diffs and create a structured, development-ready task list.

<instructions>
1. Evaluate ALL provided code diff files carefully (each file is separated by a --- FILE: header).
2. Group related line modifications into cohesive, logical development tasks across all files in this batch.
3. Assign provisional estimated_hours to each task based on relative complexity (they will be reconciled later).
4. Generate an detailed description for each task, suitable for an enterprise issue tracker (like Redmine).
5. DO NOT use words like "AI", "IA", "Artificial Intelligence", "Bot", or "Automated" in any of the titles or descriptions. Write exactly as if you are a human Senior Developer.
</instructions>

<description_requirements>
{DESCRIPTION_REQUIREMENTS}
</description_requirements>

<constraints>
- Output STRICTLY AND ONLY valid JSON.
- DO NOT wrap the response in markdown code blocks (e.g., NO ```json ... ```).
- DO NOT output any introductory greetings, conversational phrases, or reasoning text.
- Language: Every single text field MUST be written in Brazilian Portuguese.
- Escaping: Ensure all Markdown line breaks in the description are properly escaped as \\n.
- Escaping: Any double quotes inside description strings MUST be escaped as \\".
</constraints>

<output_schema>
{TASK_SCHEMA}
</output_schema>"""


def _flatten_group_tasks(group_tasks: list[dict]) -> list[dict]:
    flat: list[dict] = []
    for payload in group_tasks:
        flat.extend(payload.get("tasks", []))
    return flat


def _compact_tasks_for_merge(tasks: list[dict]) -> list[dict]:
    return [
        {
            "i": index,
            "task_title": task.get("task_title", ""),
            "category": task.get("category", ""),
            "estimated_hours": float(task.get("estimated_hours", 0)),
        }
        for index, task in enumerate(tasks)
    ]


def _validate_merge_groups(merge_groups: list, task_count: int) -> list[list[int]]:
    if not isinstance(merge_groups, list):
        raise ValueError("Mesclagem: 'merge_groups' deve ser uma lista.")

    seen: set[int] = set()
    normalized: list[list[int]] = []

    for group in merge_groups:
        if not isinstance(group, list) or not group:
            raise ValueError("Mesclagem: cada grupo deve ser uma lista não vazia de índices.")
        indices = [int(i) for i in group]
        for index in indices:
            if index < 0 or index >= task_count:
                raise ValueError(f"Mesclagem: índice inválido {index}.")
            if index in seen:
                raise ValueError(f"Mesclagem: índice duplicado {index}.")
            seen.add(index)
        normalized.append(indices)

    if seen != set(range(task_count)):
        missing = sorted(set(range(task_count)) - seen)
        raise ValueError(f"Mesclagem: índices ausentes {missing}.")

    return normalized


def _apply_merge_groups(all_tasks: list[dict], merge_groups: list[list[int]]) -> list[dict]:
    merged: list[dict] = []
    for group in merge_groups:
        group_tasks = [all_tasks[i] for i in group]
        primary = max(group_tasks, key=lambda t: len(t.get("description", "")))
        result = dict(primary)
        result["estimated_hours"] = round(
            sum(float(t.get("estimated_hours", 0)) for t in group_tasks), 2
        )

        affected_files: set[str] = set()
        for task in group_tasks:
            affected_files.update(task.get("affected_files") or [])
        if affected_files:
            result["affected_files"] = sorted(affected_files)

        merged.append(result)
    return merged


def _reconcile_hours_locally(tasks: list[dict], total_hours: float) -> dict:
    if not tasks:
        raise ValueError("Nenhuma tarefa para reconciliar.")

    target = float(total_hours)
    current = round(sum(float(t.get("estimated_hours", 0)) for t in tasks), 4)

    if current <= 0:
        per_task = round(target / len(tasks), 2)
        for task in tasks:
            task["estimated_hours"] = per_task
    else:
        ratio = target / current
        for task in tasks:
            task["estimated_hours"] = round(float(task.get("estimated_hours", 0)) * ratio, 2)

    drift = round(target - sum(float(t["estimated_hours"]) for t in tasks), 2)
    if drift != 0:
        tasks[0]["estimated_hours"] = round(float(tasks[0]["estimated_hours"]) + drift, 2)

    tasks.sort(key=lambda t: float(t.get("estimated_hours", 0)), reverse=True)

    return {
        "mathematical_reconciliation": {
            "target_total_hours": target,
            "allocation_rationale_pt": (
                f"As horas foram ajustadas proporcionalmente com base nas estimativas originais "
                f"({current:.1f}h) para totalizar exatamente {target:.1f}h. "
                f"Tarefas ordenadas da maior para a menor carga horária."
            ),
        },
        "tasks": tasks,
    }


def _apply_ai_hour_adjustments(
    tasks: list[dict],
    hours: list,
    total_hours: float,
    rationale: str,
) -> dict:
    if len(hours) != len(tasks):
        raise ValueError(
            f"Reconciliação: quantidade de horas ({len(hours)}) difere da quantidade de tarefas ({len(tasks)})."
        )

    adjusted = []
    for task, hour in zip(tasks, hours):
        updated = dict(task)
        updated["estimated_hours"] = round(float(hour), 2)
        adjusted.append(updated)

    drift = round(float(total_hours) - sum(t["estimated_hours"] for t in adjusted), 2)
    if drift != 0 and adjusted:
        adjusted[0]["estimated_hours"] = round(adjusted[0]["estimated_hours"] + drift, 2)

    adjusted.sort(key=lambda t: float(t.get("estimated_hours", 0)), reverse=True)

    return {
        "mathematical_reconciliation": {
            "target_total_hours": float(total_hours),
            "allocation_rationale_pt": rationale or (
                f"Horas ajustadas para totalizar exatamente {total_hours}h."
            ),
        },
        "tasks": adjusted,
    }


def _build_merge_tasks_prompt() -> str:
    return """You are an expert Technical Project Manager. Merge duplicate or overlapping tasks by grouping their indices.

<input_format>
You receive a JSON array of compact task summaries. Each item has:
- i: task index (integer)
- task_title: title in Portuguese
- category: Feature | Bugfix | Refactor | Test | Chore
- estimated_hours: provisional hours
</input_format>

<instructions>
1. Group indices that describe the same logical work item.
2. Keep distinct tasks in separate single-index groups.
3. Every index from 0 to N-1 MUST appear exactly once across all groups.
4. Do NOT rewrite titles or descriptions. Only decide merge groupings.
</instructions>

<constraints>
- Output STRICTLY AND ONLY valid JSON. No markdown. No commentary. No reasoning text.
- The response MUST start with { and match the schema exactly.
</constraints>

<output_schema>
""" + MERGE_RESPONSE_SCHEMA + """
</output_schema>"""


def _build_reconcile_system_prompt(total_hours: float, task_count: int) -> str:
    return f"""You are an expert Technical Project Manager. Adjust ONLY the estimated hours for an existing task list.

<input_format>
You receive a JSON array of compact tasks with fields: i, task_title, category, estimated_hours.
There are exactly {task_count} tasks with indices 0 to {task_count - 1}.
</input_format>

<instructions>
1. Review each task's scope and adjust estimated_hours for reasonableness.
2. The sum of ALL values in the "hours" array MUST EXACTLY equal {total_hours}.
3. Return hours in the SAME ORDER as the input indices (index 0 first, then 1, etc.).
4. Do NOT change titles, categories, or descriptions.
5. Do NOT add or remove tasks.
</instructions>

<constraints>
- Output STRICTLY AND ONLY valid JSON. No markdown. No commentary. No reasoning outside JSON.
- The response MUST start with {{ and match the schema exactly.
- "hours" MUST contain exactly {task_count} numbers.
- "allocation_rationale_pt" MUST be in Brazilian Portuguese (max 2 sentences).
</constraints>

<output_schema>
{RECONCILE_RESPONSE_SCHEMA.replace("[0.0, 0.0, 0.0]", f"[/* exactly {task_count} numbers summing to {total_hours} */]")}
</output_schema>"""


def analyze_diffs_grouped_with_claude(
        diff_items: list[tuple[str, str]],
        total_hours: float,
        selected_model: str,
        on_progress: Optional[ProgressCallback] = None,
        output_dir: Optional[str] = None,
) -> dict:
    """
    Processes diffs in size-based groups:
    1. Each group  -> independently creates tasks from combined diffs
    2. Merge step  -> deduplicates/consolidates all group task lists
    3. Final step  -> reconciles estimated_hours to total_hours
    """
    if not diff_items:
        raise ValueError("Nenhum diff fornecido para análise.")

    groups = _group_diff_items_by_size(diff_items)
    if not groups:
        raise ValueError("Nenhum diff com conteúdo válido encontrado para análise.")

    total_steps = len(groups) + 2  # groups + merge + reconcile
    current_step = 0
    group_tasks: list[dict] = []

    def report(message: str):
        if on_progress:
            on_progress(current_step, total_steps, message)
        print(f"[API INFO] ({current_step}/{total_steps}) {message}")

    for index, group in enumerate(groups, start=1):
        current_step = index
        label = _group_label(group)
        size_kb = _estimate_group_size(group) / 1024
        report(f"Grupo {index}/{len(groups)}: {label} (~{size_kb:.0f} KB)...")

        combined_diffs = _format_group_diffs(group)
        group_payload = _call_claude_sync(
            _build_group_create_prompt(),
            f"Code Diffs to Analyze ({len(group)} file(s)):\n\n{combined_diffs}",
            selected_model,
        )
        _validate_tasks_payload(group_payload, f"Grupo {index} ({label})")
        group_tasks.append(group_payload)
        _save_group_checkpoint(output_dir, index, group_tasks, label)

    current_step = len(groups) + 1
    report("Mesclando tarefas de todos os grupos...")
    all_tasks = _flatten_group_tasks(group_tasks)
    compact_merge_input = json.dumps(
        _compact_tasks_for_merge(all_tasks),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    merge_payload = _call_claude_sync(
        _build_merge_tasks_prompt(),
        f"Task summaries to merge ({len(all_tasks)} tasks):\n{compact_merge_input}",
        selected_model,
        max_tokens_override=4096,
        timeout=120,
    )
    merge_groups = _validate_merge_groups(merge_payload.get("merge_groups", []), len(all_tasks))
    merged_tasks = _apply_merge_groups(all_tasks, merge_groups)

    current_step = total_steps
    report(f"Reconciliando horas para total de {total_hours}h...")
    compact_reconcile_input = json.dumps(
        _compact_tasks_for_merge(merged_tasks),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    try:
        reconcile_payload = _call_claude_sync(
            _build_reconcile_system_prompt(total_hours, len(merged_tasks)),
            f"Adjust hours for these tasks:\n{compact_reconcile_input}",
            selected_model,
            max_tokens_override=4096,
            timeout=120,
        )
        hours = reconcile_payload.get("hours")
        if not isinstance(hours, list):
            raise ValueError("Reconciliação: resposta sem lista 'hours'.")
        final_payload = _apply_ai_hour_adjustments(
            merged_tasks,
            hours,
            total_hours,
            reconcile_payload.get("allocation_rationale_pt", ""),
        )
    except (ValueError, requests.exceptions.Timeout) as ex:
        print(f"[API WARN] Reconciliação via IA falhou ({ex}). Aplicando ajuste proporcional local.")
        final_payload = _reconcile_hours_locally(merged_tasks, total_hours)

    tasks = _validate_tasks_payload(final_payload, "Reconciliação")

    allocated = round(sum(float(t.get("estimated_hours", 0)) for t in tasks), 4)
    if allocated != float(total_hours):
        print(
            f"[API WARN] Soma das horas ({allocated}) difere do alvo ({total_hours}). "
            "Resultado retornado conforme resposta da API."
        )

    report("Processamento agrupado concluído.")
    return final_payload
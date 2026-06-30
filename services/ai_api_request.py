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

MODEL_CONFIGS = {
    "claude-sonnet-5": {
        "max_tokens": 8192,
        "temperature": 0.1
    },
    "claude-opus-4-8": {
        "max_tokens": 4096,
    },
    "claude-haiku-4-5-20251001": {
        "max_tokens": 8192,
        "temperature": 0.1
    }
}

TASK_SCHEMA = """{
  "tasks": [
    {
      "task_title": "Título conciso da tarefa (ex: Refatoração do módulo de Autenticação)",
      "category": "Feature | Bugfix | Refactor | Test | Chore",
      "estimated_hours": 0.0,
      "description": "**Contexto:**\\nSua explicação aqui.\\n\\n**Detalhes Técnicos:**\\nSua explicação técnica aqui.\\n\\n**Impacto / Comportamento Esperado:**\\nImpacto aqui.",
      "affected_files": ["caminho/arquivo1.java", "caminho/arquivo2.py"]
    }
  ]
}"""

DESCRIPTION_REQUIREMENTS = """The 'description' field MUST NOT be a single sentence. It must be a comprehensive, multi-paragraph string formatted in Markdown (using \\n for line breaks, ** for bolding, and - for bullet points).
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
    if "```json" in raw_content:
        raw_content = raw_content.split("```json")[-1].split("```")[0].strip()
    elif raw_content.startswith("```"):
        raw_content = raw_content.strip("`").strip()

    parsed = json.loads(raw_content)
    if not isinstance(parsed, dict):
        raise ValueError("A resposta da API não é um objeto JSON válido.")
    return parsed


def _call_claude_sync(system_prompt: str, user_content: str, selected_model: str) -> dict:
    model_params = MODEL_CONFIGS.get(selected_model, {"max_tokens": 4096})
    request_params = {
        "model": selected_model,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_content}],
    }
    request_params.update(model_params)

    try:
        response = requests.post(
            f"{CLAUDE_BASE_URL}/messages",
            headers=_get_headers(),
            json=request_params,
            timeout=300,
        )
        response.raise_for_status()
        payload = response.json()
        raw_text = payload["content"][0]["text"]
        return _extract_json_from_response(raw_text)
    except requests.exceptions.RequestException as e:
        error_text = e.response.text if e.response else str(e)
        print(f"[API ERROR] Falha na comunicação com Messages API: {error_text}")
        raise ValueError(f"Messages API Error: {error_text}") from e
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise ValueError(f"Resposta da API em formato inesperado: {e}") from e


def _validate_tasks_payload(payload: dict, step_label: str) -> list:
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError(f"{step_label}: o JSON retornado não possui a lista 'tasks' esperada.")
    return tasks


def _build_init_system_prompt() -> str:
    return f"""You are an expert Software Architect and Technical Project Manager. Your task is to analyze git diffs and create an initial structured, development-ready task list.

<instructions>
1. Evaluate the provided code diff carefully.
2. Group related line modifications into cohesive, logical development tasks.
3. Assign provisional estimated_hours to each task based on relative complexity (they will be reconciled later).
4. Generate an EXTREMELY DETAILED description for each task, suitable for an enterprise issue tracker (like Redmine).
5. DO NOT use words like "AI", "IA", "Artificial Intelligence", "Bot", or "Automated" in any of the titles or descriptions. Write exactly as if you are a human Senior Developer.
</instructions>

<description_requirements>
{DESCRIPTION_REQUIREMENTS}
</description_requirements>

<constraints>
- Language: Every single text field (titles, descriptions) MUST be written in Brazilian Portuguese.
- Escaping: Because the output is JSON, ensure all Markdown line breaks in the description are properly escaped as \\n.
- Format: Return EXCLUSIVELY a valid JSON object matching the schema below. Do not output any introductory greetings, conversational phrases, or markdown formatting blocks (such as ```json).
</constraints>

<output_schema>
{TASK_SCHEMA}
</output_schema>"""


def _build_update_system_prompt() -> str:
    return f"""You are an expert Software Architect and Technical Project Manager. You are incrementally building a development task list from multiple git diffs.

<instructions>
1. You receive the CURRENT task list (JSON) and a NEW code diff.
2. Update the task list to incorporate the new diff:
   - Merge changes into existing tasks when they belong to the same logical work item.
   - Add new tasks only when the diff introduces genuinely distinct work.
   - Remove or consolidate duplicate or overlapping tasks when appropriate.
3. Update descriptions, affected_files, categories, and provisional estimated_hours as needed.
4. DO NOT use words like "AI", "IA", "Artificial Intelligence", "Bot", or "Automated" in any of the titles or descriptions.
</instructions>

<description_requirements>
{DESCRIPTION_REQUIREMENTS}
</description_requirements>

<constraints>
- Language: Every single text field MUST be written in Brazilian Portuguese.
- Return the COMPLETE updated task list, not a partial diff of changes.
- Escaping: Ensure all Markdown line breaks in descriptions are escaped as \\n.
- Format: Return EXCLUSIVELY a valid JSON object matching the schema below. No markdown code fences.
</constraints>

<output_schema>
{TASK_SCHEMA}
</output_schema>"""


def _build_reconcile_system_prompt(total_hours: float) -> str:
    return f"""You are an expert Technical Project Manager. Your ONLY task is to review and adjust the estimated hours of an existing task list.

<instructions>
1. You receive a complete task list in JSON format. There are NO code diffs.
2. Review each task's estimated_hours for reasonableness relative to its scope.
3. Adjust estimated_hours so the sum across ALL tasks EXACTLY equals {total_hours}.
4. Do NOT change task titles, categories, descriptions, or affected_files unless a minimal edit is strictly required for consistency after hour adjustments.
5. DO NOT add or remove tasks unless two tasks are clear duplicates that must be merged to reconcile hours.
</instructions>

<constraints>
- Language: The allocation_rationale_pt MUST be written in Brazilian Portuguese.
- Mathematical Rigor: The sum of 'estimated_hours' across all items in 'tasks' MUST EXACTLY EQUAL {total_hours}.
- Format: Return EXCLUSIVELY a valid JSON object matching the schema below. No markdown code fences.
</constraints>

<output_schema>
{{
  "mathematical_reconciliation": {{
    "target_total_hours": {total_hours},
    "allocation_rationale_pt": "Explique brevemente como você ajustou as horas para garantir que a soma seja exatamente {total_hours}."
  }},
  "tasks": [
    {{
      "task_title": "Título da tarefa",
      "category": "Feature | Bugfix | Refactor | Test | Chore",
      "estimated_hours": 0.0,
      "description": "**Contexto:**\\n...\\n\\n**Detalhes Técnicos:**\\n...\\n\\n**Impacto / Comportamento Esperado:**\\n...",
      "affected_files": ["caminho/arquivo.ext"]
    }}
  ]
}}
</output_schema>

Execute your internal math calculation check first, then generate the JSON output."""


def analyze_diffs_sequential_with_claude(
    diff_items: list[tuple[str, str]],
    total_hours: float,
    selected_model: str,
    on_progress: Optional[ProgressCallback] = None,
) -> dict:
    """
    Processes diffs sequentially:
    1. First diff  -> creates base tasks JSON
    2. Next diffs  -> updates tasks JSON incrementally
    3. Final step  -> reconciles estimated_hours to total_hours (JSON only)
    """
    if not diff_items:
        raise ValueError("Nenhum diff fornecido para análise.")

    total_steps = len(diff_items) + 1
    current_step = 0

    def report(message: str):
        if on_progress:
            on_progress(current_step, total_steps, message)
        print(f"[API INFO] ({current_step}/{total_steps}) {message}")

    first_name, first_content = diff_items[0]
    content = _truncate_diff(first_content.strip())
    if not content:
        raise ValueError(f"O diff '{first_name}' está vazio.")

    current_step = 1
    report(f"Criando lista base de tarefas a partir de {first_name}...")
    tasks_payload = _call_claude_sync(
        _build_init_system_prompt(),
        f"Diff file: {first_name}\n\nCode Diff to Analyze:\n{content}",
        selected_model,
    )
    _validate_tasks_payload(tasks_payload, "Inicialização")

    for index, (diff_name, diff_content) in enumerate(diff_items[1:], start=2):
        content = _truncate_diff(diff_content.strip())
        if not content:
            print(f"[API INFO] Pulando diff vazio: {diff_name}")
            continue

        current_step = index
        report(f"Atualizando tarefas com {diff_name} ({index - 1}/{len(diff_items) - 1})...")
        current_tasks_json = json.dumps({"tasks": tasks_payload["tasks"]}, ensure_ascii=False, indent=2)
        tasks_payload = _call_claude_sync(
            _build_update_system_prompt(),
            (
                f"Current task list JSON:\n{current_tasks_json}\n\n"
                f"New diff file: {diff_name}\n\n"
                f"Code Diff to incorporate:\n{content}"
            ),
            selected_model,
        )
        _validate_tasks_payload(tasks_payload, f"Atualização ({diff_name})")

    current_step = total_steps
    report(f"Reconciliando horas para total de {total_hours}h...")
    current_tasks_json = json.dumps({"tasks": tasks_payload["tasks"]}, ensure_ascii=False, indent=2)
    final_payload = _call_claude_sync(
        _build_reconcile_system_prompt(total_hours),
        f"Task list to review and adjust hours:\n{current_tasks_json}",
        selected_model,
    )
    tasks = _validate_tasks_payload(final_payload, "Reconciliação")

    allocated = round(sum(float(t.get("estimated_hours", 0)) for t in tasks), 4)
    if allocated != float(total_hours):
        print(
            f"[API WARN] Soma das horas ({allocated}) difere do alvo ({total_hours}). "
            "Resultado retornado conforme resposta da API."
        )

    report("Processamento sequencial concluído.")
    return final_payload

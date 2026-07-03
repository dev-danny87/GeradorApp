import datetime
import os
import threading
from dataclasses import dataclass, field
from typing import List, Optional

ERROR_LOG_NAME = "registro_de_erros.txt"

_registry: Optional["ErrorRegistry"] = None


@dataclass
class ErrorEntry:
    when: str
    kind: str
    message: str
    url: str = ""
    dest_path: str = ""
    context: str = ""


@dataclass
class ErrorRegistry:
    contract_key: str
    _entries: List[ErrorEntry] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(
        self,
        *,
        kind: str,
        message: str,
        url: str = "",
        dest_path: str = "",
        context: str = "",
    ) -> None:
        entry = ErrorEntry(
            when=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            kind=kind,
            message=message,
            url=url,
            dest_path=dest_path,
            context=context,
        )
        with self._lock:
            self._entries.append(entry)

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def write(self, base_dir: str) -> Optional[str]:
        with self._lock:
            if not self._entries:
                return None
            entries = list(self._entries)

        os.makedirs(base_dir, exist_ok=True)
        path = os.path.join(base_dir, ERROR_LOG_NAME)
        generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            "Registro de erros — IPHAN",
            f"Contrato: {self.contract_key}",
            f"Gerado em: {generated_at}",
            f"Total: {len(entries)}",
            "",
        ]

        for index, entry in enumerate(entries, start=1):
            lines.append(f"[{index}] {entry.when} | {entry.kind}")
            if entry.url:
                lines.append(f"URL: {entry.url}")
            if entry.dest_path:
                lines.append(f"Destino: {entry.dest_path}")
            if entry.context:
                lines.append(f"Contexto: {entry.context}")
            lines.append(f"Erro: {entry.message}")
            lines.append("")

        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))

        return path


def begin_error_registry(contract_key: str) -> ErrorRegistry:
    global _registry
    _registry = ErrorRegistry(contract_key=contract_key)
    return _registry


def get_error_registry() -> Optional[ErrorRegistry]:
    return _registry


def record_error(
    *,
    kind: str,
    message: str,
    url: str = "",
    dest_path: str = "",
    context: str = "",
) -> None:
    registry = get_error_registry()
    if registry:
        registry.record(
            kind=kind,
            message=message,
            url=url,
            dest_path=dest_path,
            context=context,
        )


def write_error_registry(base_dir: str) -> Optional[str]:
    registry = get_error_registry()
    if not registry:
        return None
    return registry.write(base_dir)


def error_registry_summary() -> str:
    registry = get_error_registry()
    if not registry or registry.count() == 0:
        return "Registro de erros: nenhum"
    return f"Registro de erros: {ERROR_LOG_NAME} ({registry.count()} erro(s))"

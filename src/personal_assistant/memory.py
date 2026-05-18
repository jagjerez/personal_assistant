"""Memoria persistente del asistente. Es un Markdown plano editable por el usuario."""
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

_HEADER = """# Memoria del asistente personal

Este archivo se inyecta en cada sesión de Claude. Edítalo a mano si quieres forzar
algo que el asistente deba recordar. Las entradas con timestamp las añade el asistente
al rotar sesión.
"""


class Memory:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(_HEADER)

    def read(self) -> str:
        return self.path.read_text()

    def append_summary(self, summary: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        block = f"\n## Resumen de sesión — {ts}\n\n{summary.strip()}\n"
        with self.path.open("a", encoding="utf-8") as f:
            f.write(block)
        log.info("Resumen añadido a memoria (%d chars)", len(summary))

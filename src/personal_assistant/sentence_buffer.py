"""Bufer simple: acumula chunks de texto y emite oraciones completas.

Una "oración" termina con ., !, ?, : seguido de espacio/newline, o con un
salto doble. Para idiomas latinos cubre la mayoría de pausas naturales.
"""
from __future__ import annotations

import re

_BOUNDARY = re.compile(r"([.!?:]+\s+|[.!?:]+$|\n\n+)")
# Tamaño mínimo para considerar emitir una oración (evita "Sí." dividiendo demasiado).
_MIN_LEN = 4


class SentenceBuffer:
    def __init__(self):
        self._buf = ""

    def feed(self, chunk: str) -> list[str]:
        """Añade texto. Devuelve lista de oraciones completas que se pueden emitir."""
        self._buf += chunk
        out: list[str] = []
        while True:
            m = _BOUNDARY.search(self._buf)
            if not m:
                break
            end = m.end()
            sentence = self._buf[:end].strip()
            if len(sentence) >= _MIN_LEN:
                out.append(sentence)
            self._buf = self._buf[end:]
        return out

    def flush(self) -> str | None:
        s = self._buf.strip()
        self._buf = ""
        return s or None

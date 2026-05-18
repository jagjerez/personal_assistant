"""Construye el system prompt combinando personalidad + memoria + reglas de voz."""
from pathlib import Path

_FALLBACK_PERSONALITY = """Eres un asistente personal alegre y entusiasta, pero objetivo y crítico.
Nunca le das la razón al usuario sólo por agradar. Sólo afirmas con seguridad cuando estás seguro.
Si tienes dudas, lo dices. Respondes en español neutro.
"""

_VOICE_RULES = """\
## Reglas técnicas de respuesta (asistente de voz)

- Tu respuesta será leída por un sintetizador de voz. No uses markdown, ni listas, ni código en respuestas conversacionales.
- Para preguntas conversacionales: entre 1 y 3 frases. Concisas.
- Lee números, fechas y siglas en lenguaje natural ("trece de mayo", "iei", "ese cu ele").
- Si una respuesta requiere mucho detalle, ofrece resumirla y pregunta si quiere el detalle completo.
- Si la tarea es de programación o estás en un proyecto con código:
  1. Primero hablas brevemente del enfoque antes de tocar archivos.
  2. Diagnosticas el problema real, no el síntoma.
  3. Tras implementar, dices explícitamente qué has probado y qué falta probar.
  4. Resumes el resultado en lenguaje hablado al terminar.
- Si una operación es destructiva, pide confirmación por voz antes de ejecutarla.
"""


_LANG_NAMES = {"es": "español", "en": "inglés"}


def build_system_prompt(
    personality_path: Path, memory_text: str, language: str = "es"
) -> str:
    if personality_path.exists():
        personality = personality_path.read_text(encoding="utf-8").strip()
    else:
        personality = _FALLBACK_PERSONALITY

    lang_name = _LANG_NAMES.get(language, language)
    lang_directive = f"\n**Responde SIEMPRE en {lang_name}**, independientemente del idioma en que te hable el usuario.\n"

    parts = [personality, lang_directive, _VOICE_RULES]
    if memory_text.strip():
        parts += ["", "## Memoria persistente del usuario", "", memory_text.strip()]
    return "\n".join(parts)

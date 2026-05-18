"""Catálogo curado de voces Piper + descarga on-demand.

URLs siguen el patrón de https://huggingface.co/rhasspy/piper-voices
"""
from __future__ import annotations

import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


@dataclass(frozen=True)
class Voice:
    id: str          # ej. "es_ES-sharvard-medium"
    name: str        # nombre amigable para UI
    lang: str        # "es", "en"
    locale: str      # "es_ES", "en_US", "en_GB"
    gender: str      # "F" | "M"
    rel_path: str    # ruta relativa bajo PIPER_BASE (sin .onnx)

    @property
    def onnx_url(self) -> str:
        return f"{PIPER_BASE}/{self.rel_path}.onnx"

    @property
    def json_url(self) -> str:
        return f"{PIPER_BASE}/{self.rel_path}.onnx.json"


# Catálogo curado — voces que sé que existen en piper-voices con buena calidad.
VOICES: list[Voice] = [
    # Español de España
    Voice("es_ES-sharvard-medium", "Sharvard (Mujer ES)", "es", "es_ES", "F",
          "es/es_ES/sharvard/medium/es_ES-sharvard-medium"),
    Voice("es_ES-mls_9972-low",    "MLS (Mujer ES, voz natural)", "es", "es_ES", "F",
          "es/es_ES/mls_9972/low/es_ES-mls_9972-low"),
    Voice("es_ES-davefx-medium",   "Davefx (Hombre ES)", "es", "es_ES", "M",
          "es/es_ES/davefx/medium/es_ES-davefx-medium"),
    Voice("es_ES-carlfm-x_low",    "Carlfm (Hombre ES, rápido)", "es", "es_ES", "M",
          "es/es_ES/carlfm/x_low/es_ES-carlfm-x_low"),
    # Español de México
    Voice("es_MX-claude-high",     "Claude (Hombre MX, alta calidad)", "es", "es_MX", "M",
          "es/es_MX/claude/high/es_MX-claude-high"),
    Voice("es_MX-ald-medium",      "Ald (Hombre MX)", "es", "es_MX", "M",
          "es/es_MX/ald/medium/es_MX-ald-medium"),
    # Inglés US
    Voice("en_US-amy-medium",      "Amy (Mujer EN-US)", "en", "en_US", "F",
          "en/en_US/amy/medium/en_US-amy-medium"),
    Voice("en_US-hfc_female-medium", "HFC (Mujer EN-US)", "en", "en_US", "F",
          "en/en_US/hfc_female/medium/en_US-hfc_female-medium"),
    Voice("en_US-lessac-medium",   "Lessac (Mujer EN-US)", "en", "en_US", "F",
          "en/en_US/lessac/medium/en_US-lessac-medium"),
    Voice("en_US-ryan-high",       "Ryan (Hombre EN-US)", "en", "en_US", "M",
          "en/en_US/ryan/high/en_US-ryan-high"),
    # Inglés UK
    Voice("en_GB-jenny_dioco-medium", "Jenny (Mujer EN-GB)", "en", "en_GB", "F",
          "en/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium"),
    Voice("en_GB-alan-medium",     "Alan (Hombre EN-GB)", "en", "en_GB", "M",
          "en/en_GB/alan/medium/en_GB-alan-medium"),
]


# Frases de demo por idioma — el usuario las oye en el menú de selección.
DEMO_TEXTS = {
    "es": "Hola. Soy tu asistente personal por voz. Pulsa Super equis para empezar a hablar conmigo.",
    "en": "Hi. I'm your voice assistant. Press Super X to start talking with me.",
}


def voices_for_language(lang: str) -> list[Voice]:
    return [v for v in VOICES if v.lang == lang]


def get_voice(voice_id: str) -> Voice | None:
    for v in VOICES:
        if v.id == voice_id:
            return v
    return None


def voice_dir() -> Path:
    return Path("~/.local/share/personal-assistant/voices").expanduser()


def voice_path(voice_id: str) -> Path:
    return voice_dir() / f"{voice_id}.onnx"


def is_downloaded(voice_id: str) -> bool:
    p = voice_path(voice_id)
    return p.exists() and p.with_suffix(".onnx.json").exists()


def download_voice(voice: Voice) -> Path:
    """Descarga la voz si no está en local. Devuelve la ruta del .onnx.

    Síncrono — no llamar desde el thread Qt directamente, usar QThread o run_in_executor.
    """
    target_dir = voice_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    onnx = target_dir / f"{voice.id}.onnx"
    meta = target_dir / f"{voice.id}.onnx.json"

    if onnx.exists() and meta.exists():
        return onnx

    log.info("Descargando voz %s desde HuggingFace...", voice.id)
    for url, dst in ((voice.onnx_url, onnx), (voice.json_url, meta)):
        log.info("  ↳ %s", url)
        tmp = dst.with_suffix(dst.suffix + ".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.rename(dst)
    log.info("Voz %s descargada", voice.id)
    return onnx

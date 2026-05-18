"""Catálogo curado de voces (ElevenLabs + Piper) + descarga on-demand.

Engines:
- "elevenlabs": neural cloud. Mejor calidad. Necesita API key + plan Starter+.
- "piper": local ligero (~60MB por voz). Voz robótica pero offline y gratis.
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
    id: str          # ID interno (XTTS: nombre speaker, Piper: nombre modelo)
    engine: str      # "xtts" | "piper"
    name: str
    lang: str        # "es", "en", "*" para multilingüe
    locale: str      # "es_ES", "en_US", "*"
    gender: str      # "F" | "M"
    rel_path: str = ""   # sólo Piper: ruta relativa bajo PIPER_BASE

    @property
    def piper_onnx_url(self) -> str:
        return f"{PIPER_BASE}/{self.rel_path}.onnx"

    @property
    def piper_json_url(self) -> str:
        return f"{PIPER_BASE}/{self.rel_path}.onnx.json"


# Catálogo curado por engine.
VOICES: list[Voice] = [
    # ───── ElevenLabs (neural cloud, multilingüe v2) ─────
    # IDs de voces "premade" estables. Modelo eleven_multilingual_v2 hace cualquier idioma.
    Voice("21m00Tcm4TlvDq8ikWAM", "elevenlabs", "Rachel — neural cloud (mujer)",   "*", "*", "F"),
    Voice("EXAVITQu4vr4xnSDxMaL", "elevenlabs", "Bella — neural cloud (mujer)",    "*", "*", "F"),
    Voice("MF3mGyEYCl7XYWbV9V6O", "elevenlabs", "Elli — neural cloud (mujer)",     "*", "*", "F"),
    Voice("AZnzlk1XvdvUeBnXmlld", "elevenlabs", "Domi — neural cloud (mujer)",     "*", "*", "F"),
    Voice("XB0fDUnXU5powFXDhCwa", "elevenlabs", "Charlotte — neural cloud (mujer)","*", "*", "F"),
    Voice("ThT5KcBeYPX3keUQqHPh", "elevenlabs", "Dorothy — neural cloud (mujer)",  "*", "*", "F"),
    Voice("ErXwobaYiN019PkySvjV", "elevenlabs", "Antoni — neural cloud (hombre)",  "*", "*", "M"),
    Voice("VR6AewLTigWG4xSOukaG", "elevenlabs", "Arnold — neural cloud (hombre)",  "*", "*", "M"),
    Voice("pNInz6obpgDQGcFmaJgB", "elevenlabs", "Adam — neural cloud (hombre)",    "*", "*", "M"),
    Voice("yoZ06aMxZJJ28mfd3POQ", "elevenlabs", "Sam — neural cloud (hombre)",     "*", "*", "M"),

    # ───── PIPER (local ligero, fallback offline) ─────
    Voice("es_ES-sharvard-medium", "piper", "Sharvard (Mujer ES) — piper", "es", "es_ES", "F",
          "es/es_ES/sharvard/medium/es_ES-sharvard-medium"),
    Voice("es_ES-mls_9972-low",    "piper", "MLS (Mujer ES) — piper", "es", "es_ES", "F",
          "es/es_ES/mls_9972/low/es_ES-mls_9972-low"),
    Voice("es_ES-davefx-medium",   "piper", "Davefx (Hombre ES) — piper", "es", "es_ES", "M",
          "es/es_ES/davefx/medium/es_ES-davefx-medium"),
    Voice("en_US-amy-medium",      "piper", "Amy (Mujer EN-US) — piper", "en", "en_US", "F",
          "en/en_US/amy/medium/en_US-amy-medium"),
    Voice("en_US-hfc_female-medium","piper", "HFC (Mujer EN-US) — piper", "en", "en_US", "F",
          "en/en_US/hfc_female/medium/en_US-hfc_female-medium"),
    Voice("en_US-ryan-high",       "piper", "Ryan (Hombre EN-US) — piper", "en", "en_US", "M",
          "en/en_US/ryan/high/en_US-ryan-high"),
]


DEMO_TEXTS = {
    "es": "Hola. Soy tu asistente personal por voz. Pulsa Super equis para empezar a hablar conmigo.",
    "en": "Hi. I'm your personal voice assistant. Press Super X to start talking with me.",
}


def voices_for_language(lang: str) -> list[Voice]:
    """Voces compatibles con un idioma. XTTS (lang='*') aparece en todos."""
    return [v for v in VOICES if v.lang == lang or v.lang == "*"]


def get_voice(voice_id: str) -> Voice | None:
    for v in VOICES:
        if v.id == voice_id:
            return v
    return None


def voice_dir() -> Path:
    return Path("~/.local/share/personal-assistant/voices").expanduser()


def piper_voice_path(voice_id: str) -> Path:
    return voice_dir() / f"{voice_id}.onnx"


def is_downloaded(voice: Voice) -> bool:
    """ElevenLabs es cloud → siempre 'disponible'. Piper se valida fichero a fichero."""
    if voice.engine == "elevenlabs":
        return True
    p = piper_voice_path(voice.id)
    return p.exists() and p.with_suffix(".onnx.json").exists()


def download_voice(voice: Voice) -> None:
    """Descarga la voz si no está. Síncrono — usar desde QThread o run_in_executor."""
    if voice.engine == "elevenlabs":
        return  # cloud, no hay nada que descargar

    target_dir = voice_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    onnx = target_dir / f"{voice.id}.onnx"
    meta = target_dir / f"{voice.id}.onnx.json"
    if onnx.exists() and meta.exists():
        return
    log.info("Descargando voz Piper %s...", voice.id)
    for url, dst in ((voice.piper_onnx_url, onnx), (voice.piper_json_url, meta)):
        log.info("  ↳ %s", url)
        tmp = dst.with_suffix(dst.suffix + ".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.rename(dst)
    log.info("Voz Piper %s descargada", voice.id)

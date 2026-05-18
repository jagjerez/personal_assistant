"""Backend XTTS-v2 (Coqui) — TTS neural multilingüe.

- Modelo único de 1.8GB que habla 16 idiomas con cualquiera de sus speakers.
- Inferencia más lenta que Piper (~1-3s GPU / ~5-10s CPU para 3s de audio).
- Calidad casi humana, especialmente en EN y ES.
- Usa onnxruntime + PyTorch internamente.

Notas:
- Requiere aceptar la licencia CPML (no comercial). Bypass programático:
  env var COQUI_TOS_AGREED=1 (la fijamos antes de importar TTS).
- Primer arranque: descarga el modelo a ~/.local/share/tts/tts_models--... .
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

# Bypass del prompt interactivo de licencia (sólo se acepta la CPML al cargar).
os.environ.setdefault("COQUI_TOS_AGREED", "1")

XTTS_MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"

# Mapeo idioma → código XTTS
XTTS_LANG_MAP = {
    "es": "es",
    "en": "en",
    "fr": "fr",
    "it": "it",
    "pt": "pt",
    "de": "de",
}


def _model_dir() -> Path:
    return Path("~/.local/share/tts").expanduser()


def is_xtts_downloaded() -> bool:
    d = _model_dir()
    # El nombre real del directorio contiene puntos convertidos en --
    return any(d.glob("tts_models--multilingual--multi-dataset--xtts_v2*"))


def ensure_xtts_model() -> None:
    """Fuerza la descarga del modelo si aún no está. Síncrono y bloqueante."""
    if is_xtts_downloaded():
        return
    log.info("Descargando modelo XTTS-v2 (~1.8GB). Sólo la primera vez.")
    # Importar TTS dispara la descarga vía ManageModel
    from TTS.api import TTS as _XTTS_API
    _ = _XTTS_API(XTTS_MODEL_NAME, progress_bar=True)
    log.info("Modelo XTTS-v2 descargado")


class XTTSBackend:
    """Backend XTTS-v2 que carga el modelo una vez y reusa para cada speak()."""

    def __init__(self, device: str = "cuda"):
        from TTS.api import TTS as _XTTS_API
        log.info("Cargando XTTS-v2 en %s (puede tardar ~20s)...", device)
        try:
            self.tts = _XTTS_API(XTTS_MODEL_NAME, progress_bar=False)
        except Exception:
            log.exception("Error cargando XTTS-v2; reintentando descarga")
            ensure_xtts_model()
            self.tts = _XTTS_API(XTTS_MODEL_NAME, progress_bar=False)
        try:
            self.tts.to(device)
            self.device = device
        except Exception as e:
            log.warning("Device '%s' falló (%s) — cayendo a CPU", device, e)
            self.tts.to("cpu")
            self.device = "cpu"
        self.sample_rate = 24000
        log.info("XTTS-v2 listo (device=%s, sr=%d)", self.device, self.sample_rate)

    def _xtts_lang(self, language: str) -> str:
        return XTTS_LANG_MAP.get(language, "en")

    async def speak(
        self,
        text: str,
        voice_id: str,
        language: str = "en",
        speed: float = 1.0,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> None:
        loop = asyncio.get_running_loop()
        samples = await loop.run_in_executor(
            None, self._synthesize, text, voice_id, language, speed
        )
        if cancel_event and cancel_event.is_set():
            return
        if samples is None or len(samples) == 0:
            return
        await loop.run_in_executor(None, self._play, samples, cancel_event)

    def _synthesize(
        self, text: str, speaker: str, language: str, speed: float
    ) -> np.ndarray:
        try:
            wav = self.tts.tts(
                text=text,
                speaker=speaker,
                language=self._xtts_lang(language),
                speed=speed,
            )
            arr = np.asarray(wav, dtype=np.float32)
            return arr
        except Exception:
            log.exception("Error sintetizando con XTTS")
            return np.zeros(0, dtype=np.float32)
        finally:
            # Reduce fragmentación de VRAM entre síntesis.
            if self.device == "cuda":
                try:
                    import torch
                    torch.cuda.empty_cache()
                except Exception:
                    pass

    def _play(self, samples: np.ndarray, cancel_event: Optional[asyncio.Event]) -> None:
        sd.play(samples, self.sample_rate)
        try:
            while sd.get_stream().active:
                if cancel_event and cancel_event.is_set():
                    sd.stop()
                    return
                sd.sleep(100)
        except Exception:
            sd.wait()

    def play_demo(
        self, text: str, voice_id: str, language: str = "en", speed: float = 1.0
    ) -> None:
        samples = self._synthesize(text, voice_id, language, speed)
        if len(samples) == 0:
            return
        sd.play(samples, self.sample_rate)
        sd.wait()

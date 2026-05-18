"""Transcripción con faster-whisper."""
import asyncio
import logging
import os
import tempfile
from pathlib import Path

from faster_whisper import WhisperModel

from .config import WhisperConfig

log = logging.getLogger(__name__)


_MODEL_SIZES_MB = {"tiny": 75, "base": 145, "small": 480, "medium": 1530, "large-v3": 3100}


def _is_cached(model_name: str) -> bool:
    cache = Path(os.environ.get("HF_HOME", "~/.cache/huggingface")).expanduser() / "hub"
    pattern = f"models--Systran--faster-whisper-{model_name}"
    return any(cache.glob(f"{pattern}*"))


class STT:
    def __init__(self, cfg: WhisperConfig):
        if not _is_cached(cfg.model):
            mb = _MODEL_SIZES_MB.get(cfg.model, 1500)
            log.info(
                "Descargando modelo Whisper '%s' (~%d MB). Sólo la primera vez. "
                "Tarda unos minutos según tu conexión...",
                cfg.model, mb,
            )
        else:
            log.info("Cargando Whisper '%s' desde caché (compute_type=%s)...",
                     cfg.model, cfg.compute_type)
        self.model = WhisperModel(
            cfg.model, device=cfg.device, compute_type=cfg.compute_type
        )
        self.language = cfg.language
        log.info("Whisper listo (device=%s, compute_type=%s)", cfg.device, cfg.compute_type)

    async def transcribe(self, wav_bytes: bytes) -> str:
        return await asyncio.get_running_loop().run_in_executor(
            None, self._transcribe_sync, wav_bytes
        )

    def _transcribe_sync(self, wav_bytes: bytes) -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            path = Path(f.name)
        try:
            segments, _ = self.model.transcribe(
                str(path),
                language=self.language,
                vad_filter=True,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            return text
        finally:
            path.unlink(missing_ok=True)

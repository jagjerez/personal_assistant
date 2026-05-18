"""Dispatcher TTS: enruta a ElevenLabs, XTTS o Piper según la voz seleccionada."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .config import TTSConfig
from .voices import Voice, get_voice

log = logging.getLogger(__name__)


class TTS:
    def __init__(self, cfg: TTSConfig, language: str = "es"):
        self.cfg = cfg
        self.language = language
        self._engines: dict[str, object] = {}
        self.current_voice: Voice | None = None
        self.set_voice(cfg.voice)

    def _engine(self, engine_name: str):
        if engine_name not in self._engines:
            if engine_name == "elevenlabs":
                from .tts_elevenlabs import ElevenLabsBackend
                self._engines[engine_name] = ElevenLabsBackend(
                    api_key=self.cfg.api_key,
                    model=self.cfg.elevenlabs_model,
                )
            elif engine_name == "xtts":
                from .tts_xtts import XTTSBackend
                self._engines[engine_name] = XTTSBackend(device=self.cfg.device)
            elif engine_name == "piper":
                from .tts_piper import PiperBackend
                self._engines[engine_name] = PiperBackend()
            else:
                raise ValueError(f"Engine desconocido: {engine_name}")
        return self._engines[engine_name]

    def set_voice(self, voice_id: str) -> None:
        v = get_voice(voice_id)
        if v is None:
            raise ValueError(f"Voz desconocida en catálogo: {voice_id}")
        self.current_voice = v
        self._engine(v.engine)
        log.info("Voz activa: %s (%s)", v.name, v.engine)

    def set_language(self, lang: str) -> None:
        self.language = lang

    async def speak(self, text: str, cancel_event: Optional[asyncio.Event] = None) -> None:
        v = self.current_voice
        if v is None or not text.strip():
            return
        engine = self._engine(v.engine)
        await engine.speak(
            text, v.id, language=self.language,
            speed=self.cfg.speed, cancel_event=cancel_event,
        )

    def play_demo(self, text: str, voice_id: str, language: Optional[str] = None) -> None:
        v = get_voice(voice_id)
        if v is None:
            log.warning("Demo: voz desconocida %s", voice_id)
            return
        engine = self._engine(v.engine)
        engine.play_demo(text, v.id, language=language or self.language, speed=self.cfg.speed)

"""Orquestador: hotkey → grabación → STT → Claude → TTS, con cancelación."""
import asyncio
import logging
from enum import Enum
from pathlib import Path
from typing import Optional

from .claude_session import ClaudeSession
from .config import Config
from .hotkey import hotkey_events
from .indicator import (
    STATE_IDLE,
    STATE_RECORDING,
    STATE_SPEAKING,
    STATE_THINKING,
    Overlay,
)
from .memory import Memory
from .personality import build_system_prompt
from .recorder import play_beep, record_until_silence
from .stt import STT
from .tts import TTS

log = logging.getLogger(__name__)


class State(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PROCESSING = "processing"
    SPEAKING = "speaking"


class Daemon:
    def __init__(self, cfg: Config, indicator: Optional[Overlay] = None):
        self.cfg = cfg
        self.indicator = indicator
        self.state = State.IDLE

        self.memory = Memory(cfg.paths.memory_file)
        self.stt = STT(cfg.whisper)
        self.tts = TTS(cfg.tts, language=cfg.claude.language)

        def rebuild_system_prompt() -> str:
            return build_system_prompt(
                cfg.paths.personality_file,
                self.memory.read(),
                language=cfg.claude.language,
            )

        self._rebuild_system_prompt = rebuild_system_prompt
        self.claude = ClaudeSession(
            cfg=cfg.claude,
            system_prompt=rebuild_system_prompt(),
            memory=self.memory,
            on_rotate=rebuild_system_prompt,
        )

        self._pipeline_task: Optional[asyncio.Task] = None
        self._cancel_event = asyncio.Event()
        self._stop_event = asyncio.Event()

    # ---- API pública usada desde Qt (thread principal) ----

    def apply_voice(self, voice_id: str) -> None:
        """Cambia la voz en caliente (cualquier engine)."""
        try:
            self.tts.set_voice(voice_id)
        except Exception:
            log.exception("Error cambiando voz")

    def apply_language(self, language: str) -> None:
        """Cambia el idioma de transcripción, respuesta y TTS."""
        self.cfg.whisper.language = language
        self.cfg.claude.language = language
        self.stt.language = language
        self.tts.set_language(language)
        self.claude.system_prompt = self._rebuild_system_prompt()
        log.info("Idioma cambiado a %s", language)

    # ---- helpers overlay ----
    def _set_overlay(self, state: str) -> None:
        if self.indicator is not None:
            self.indicator.sig_state.emit(state)

    def _push_level(self, level: float) -> None:
        if self.indicator is not None:
            self.indicator.sig_level.emit(level)

    async def run(self) -> None:
        log.info(
            "Asistente listo. Pulsa %s+%s para hablar.",
            self.cfg.hotkey.modifier, self.cfg.hotkey.key,
        )
        async for _ in hotkey_events(self.cfg.hotkey):
            await self._on_hotkey()

    async def _on_hotkey(self) -> None:
        if self.state == State.IDLE:
            self._cancel_event = asyncio.Event()
            self._stop_event = asyncio.Event()
            self._pipeline_task = asyncio.create_task(self._pipeline())
        elif self.state == State.RECORDING:
            # Parar grabación graciosamente y procesar lo grabado.
            log.info("Hotkey en RECORDING — terminando grabación y procesando")
            self._stop_event.set()
        else:  # PROCESSING o SPEAKING → cancelar todo
            log.info("Hotkey en %s — cancelando", self.state.value)
            self._cancel_event.set()
            if self._pipeline_task and not self._pipeline_task.done():
                self._pipeline_task.cancel()
            self._set_overlay(STATE_IDLE)

    async def _pipeline(self) -> None:
        try:
            self.state = State.RECORDING
            self._set_overlay(STATE_RECORDING)
            if self.cfg.audio.beep:
                play_beep(880, 60)
            log.info("Grabando...")
            wav = await record_until_silence(
                self.cfg.vad,
                cancel_event=self._cancel_event,
                stop_event=self._stop_event,
                on_level=self._push_level,
            )
            if self.cfg.audio.beep:
                play_beep(660, 60)
            if not wav:
                log.info("Sin audio útil")
                return

            self.state = State.PROCESSING
            self._set_overlay(STATE_THINKING)
            log.info("Transcribiendo...")
            text = await self.stt.transcribe(wav)
            if not text:
                log.info("Transcripción vacía")
                return
            log.info("Usuario: %s", text)

            response = await self.claude.ask(text)
            if not response:
                log.warning("Respuesta vacía de Claude")
                return
            log.info("Asistente: %s", response)

            self.state = State.SPEAKING
            self._set_overlay(STATE_SPEAKING)
            await self.tts.speak(response, self._cancel_event)
        except asyncio.CancelledError:
            log.info("Pipeline cancelado")
        except Exception:
            log.exception("Error en pipeline")
        finally:
            self.state = State.IDLE
            self._set_overlay(STATE_IDLE)

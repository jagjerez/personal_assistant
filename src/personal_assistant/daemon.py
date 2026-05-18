"""Orquestador concurrente.

Diseño:
- El usuario puede iniciar una nueva grabación SIN esperar a que termine la
  respuesta anterior. La grabación cancela cualquier reproducción en curso.
- Cada turno (grabar+transcribir+Claude+TTS) es una Task asyncio independiente.
- Las salidas de TTS se serializan via una cola FIFO de "task outputs": cada
  task vuelca sus oraciones a un canal propio y un consumidor único reproduce
  los canales en orden de llegada.
- Streaming sentence-by-sentence: Claude streamea, cada oración pasa al canal
  inmediatamente — la primera empieza a sonar mientras Claude sigue generando.
"""
import asyncio
import logging
import uuid
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
from .sentence_buffer import SentenceBuffer
from .stt import STT
from .tts import TTS

log = logging.getLogger(__name__)


class _TaskOutput:
    """Canal por-turno: el productor (Claude+sentences) llena, el consumidor reproduce."""

    def __init__(self, task_id: str):
        self.id = task_id
        self.q: asyncio.Queue[Optional[str]] = asyncio.Queue()

    async def emit(self, sentence: str) -> None:
        await self.q.put(sentence)

    def close(self) -> None:
        self.q.put_nowait(None)


class Daemon:
    def __init__(self, cfg: Config, indicator: Optional[Overlay] = None):
        self.cfg = cfg
        self.indicator = indicator

        self.memory = Memory(cfg.paths.memory_file)
        self.stt = STT(cfg.whisper)
        self.tts = TTS(cfg.tts, language=cfg.claude.language)

        def rebuild_system_prompt() -> str:
            return build_system_prompt(
                cfg.paths.personality_file, self.memory.read(),
                language=cfg.claude.language,
            )

        self._rebuild_system_prompt = rebuild_system_prompt
        self.claude = ClaudeSession(
            cfg=cfg.claude,
            system_prompt=rebuild_system_prompt(),
            memory=self.memory,
            on_rotate=rebuild_system_prompt,
        )

        # Estado para overlay
        self._recording = False
        self._speaking = False
        self._claude_in_flight = 0

        # Eventos para grabación actual
        self._record_stop = asyncio.Event()   # parar y procesar
        self._record_cancel = asyncio.Event()  # descartar
        self._speech_cancel = asyncio.Event()  # cancelar TTS en curso

        # Cola FIFO de TaskOutputs — el consumidor único reproduce de uno en uno
        self._outputs: asyncio.Queue[_TaskOutput] = asyncio.Queue()
        self._consumer_task: Optional[asyncio.Task] = None

    # ---- API usada desde Qt (thread principal) ----

    def apply_voice(self, voice_id: str) -> None:
        try:
            self.tts.set_voice(voice_id)
        except Exception:
            log.exception("Error cambiando voz")

    def apply_language(self, language: str) -> None:
        self.cfg.whisper.language = language
        self.cfg.claude.language = language
        self.stt.language = language
        self.tts.set_language(language)
        self.claude.system_prompt = self._rebuild_system_prompt()
        log.info("Idioma cambiado a %s", language)

    # ---- Overlay helpers ----

    def _overlay_state(self) -> str:
        if self._recording:
            return STATE_RECORDING
        if self._speaking:
            return STATE_SPEAKING
        if self._claude_in_flight > 0:
            return STATE_THINKING
        return STATE_IDLE

    def _refresh_overlay(self) -> None:
        if self.indicator is not None:
            self.indicator.sig_state.emit(self._overlay_state())

    def _push_level(self, level: float) -> None:
        if self.indicator is not None:
            self.indicator.sig_level.emit(level)

    # ---- Loop principal ----

    async def run(self) -> None:
        log.info(
            "Asistente listo. Pulsa %s+%s para hablar.",
            self.cfg.hotkey.modifier, self.cfg.hotkey.key,
        )
        self._consumer_task = asyncio.create_task(self._tts_consumer())
        async for _ in hotkey_events(self.cfg.hotkey):
            await self._on_hotkey()

    # ---- Manejo de hotkey ----

    async def _on_hotkey(self) -> None:
        if self._recording:
            # Hotkey durante grabación: parar y procesar lo grabado
            log.info("Hotkey RECORDING → parar y procesar")
            self._record_stop.set()
            return

        # No estamos grabando — empezamos grabación nueva.
        # Si estaba sonando algo previo, lo cancelamos para dar prioridad a la voz nueva.
        if self._speaking:
            log.info("Hotkey durante SPEAKING → cancelo audio y grabo")
            self._speech_cancel.set()

        # Disparamos el turno como Task — el daemon vuelve a estar listo para más hotkeys.
        asyncio.create_task(self._handle_turn())

    # ---- Turno completo: record → STT → Claude stream → TTS canal ----

    async def _handle_turn(self) -> None:
        turn_id = uuid.uuid4().hex[:6]
        try:
            wav = await self._record(turn_id)
            if not wav:
                return
            text = await self._transcribe(wav, turn_id)
            if not text:
                return
            output = _TaskOutput(turn_id)
            await self._outputs.put(output)
            self._claude_in_flight += 1
            self._refresh_overlay()
            try:
                await self._stream_claude_to_output(text, output)
            finally:
                self._claude_in_flight = max(0, self._claude_in_flight - 1)
                output.close()
                self._refresh_overlay()
        except asyncio.CancelledError:
            log.info("[%s] turno cancelado", turn_id)
        except Exception:
            log.exception("[%s] error en turno", turn_id)

    async def _record(self, turn_id: str) -> Optional[bytes]:
        self._recording = True
        self._refresh_overlay()
        self._record_stop = asyncio.Event()
        self._record_cancel = asyncio.Event()
        try:
            if self.cfg.audio.beep:
                play_beep(880, 60)
            log.info("[%s] Grabando", turn_id)
            wav = await record_until_silence(
                self.cfg.vad,
                cancel_event=self._record_cancel,
                stop_event=self._record_stop,
                on_level=self._push_level,
            )
            if self.cfg.audio.beep:
                play_beep(660, 60)
            return wav
        finally:
            self._recording = False
            self._refresh_overlay()

    async def _transcribe(self, wav: bytes, turn_id: str) -> Optional[str]:
        log.info("[%s] Transcribiendo", turn_id)
        text = await self.stt.transcribe(wav)
        if not text:
            log.info("[%s] Transcripción vacía", turn_id)
            return None
        log.info("[%s] Usuario: %s", turn_id, text)
        return text

    async def _stream_claude_to_output(self, text: str, output: _TaskOutput) -> None:
        log.info("[%s] Llamando a Claude (stream)", output.id)
        buf = SentenceBuffer()
        async for chunk in self.claude.ask_stream(text):
            for sentence in buf.feed(chunk):
                log.debug("[%s] sentence → %s", output.id, sentence[:60])
                await output.emit(sentence)
        final = buf.flush()
        if final:
            await output.emit(final)
        log.info("[%s] Claude completo", output.id)

    # ---- Consumidor único de TTS — procesa outputs en orden FIFO ----

    async def _tts_consumer(self) -> None:
        while True:
            output = await self._outputs.get()
            self._speaking = True
            self._speech_cancel = asyncio.Event()
            self._refresh_overlay()
            try:
                while True:
                    sentence = await output.q.get()
                    if sentence is None:
                        break
                    if self._speech_cancel.is_set():
                        # Drena lo que quede para no contaminar siguiente turno
                        continue
                    try:
                        await self.tts.speak(sentence, cancel_event=self._speech_cancel)
                    except Exception:
                        log.exception("Error TTS")
            finally:
                self._speaking = False
                self._refresh_overlay()

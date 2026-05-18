"""Backend ElevenLabs TTS — neural cloud, streaming PCM real.

API key vía env var ELEVENLABS_API_KEY (preferido) o cfg.tts.api_key.

Streaming: la SDK devuelve un generador de bytes PCM mientras ElevenLabs
sintetiza. Los escribimos a un OutputStream de sounddevice → primer audio
suena ~300-500ms tras enviar el texto, no hay que esperar al final.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Iterable, Optional

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

# Output format soportado por sounddevice sin reencoding.
PCM_SAMPLE_RATE = 22050
OUTPUT_FORMAT = "pcm_22050"
DEFAULT_MODEL = "eleven_multilingual_v2"


class ElevenLabsBackend:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
    ):
        from elevenlabs.client import ElevenLabs
        key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            raise RuntimeError(
                "ElevenLabs requiere ELEVENLABS_API_KEY (env var) o cfg.tts.api_key."
            )
        self.client = ElevenLabs(api_key=key)
        self.model = model
        self.sample_rate = PCM_SAMPLE_RATE
        log.info("ElevenLabs listo (model=%s, sr=%d Hz)", model, self.sample_rate)

    # ---- streaming chunks desde ElevenLabs ----

    def _request_chunks(self, text: str, voice_id: str) -> Iterable[bytes]:
        """Devuelve un iterador de bytes PCM tal y como llegan de ElevenLabs."""
        return self.client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id=self.model,
            output_format=OUTPUT_FORMAT,
        )

    # ---- API que usa el dispatcher ----

    async def speak(
        self,
        text: str,
        voice_id: str,
        language: str = "",  # ElevenLabs usa el modelo multilingüe, no hace falta lang
        speed: float = 1.0,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> None:
        if not text.strip():
            return
        # Reproducción streaming en thread (sounddevice.OutputStream bloquea).
        await asyncio.get_running_loop().run_in_executor(
            None, self._stream_play, text, voice_id, cancel_event
        )

    def _stream_play(
        self, text: str, voice_id: str, cancel_event: Optional[asyncio.Event]
    ) -> None:
        """Reproduce chunks PCM tal y como llegan del HTTP stream de ElevenLabs."""
        try:
            chunks = self._request_chunks(text, voice_id)
        except Exception:
            log.exception("Error pidiendo síntesis a ElevenLabs")
            return

        with sd.OutputStream(
            samplerate=self.sample_rate, channels=1, dtype="int16",
            blocksize=0,
        ) as stream:
            for chunk_bytes in chunks:
                if cancel_event is not None and cancel_event.is_set():
                    break
                if not chunk_bytes:
                    continue
                arr = np.frombuffer(chunk_bytes, dtype=np.int16)
                if arr.size == 0:
                    continue
                try:
                    stream.write(arr)
                except sd.PortAudioError as e:
                    log.warning("PortAudio write falló: %s", e)
                    break

    def play_demo(
        self, text: str, voice_id: str, language: str = "", speed: float = 1.0
    ) -> None:
        """Reproduce sincrónicamente. Usado por el menú."""
        self._stream_play(text, voice_id, None)

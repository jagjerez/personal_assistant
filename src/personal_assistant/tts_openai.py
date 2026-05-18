"""Backend OpenAI TTS — streaming PCM 24 kHz.

Modelo `tts-1` (rápido, calidad muy buena) o `tts-1-hd` (~2x más lento).
API key vía env OPENAI_API_KEY o cfg.tts.openai_api_key.
Pay-as-you-go: ~$0.015 / 1000 chars (tts-1), ~$0.030 / 1000 chars (tts-1-hd).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

PCM_SAMPLE_RATE = 24000   # OpenAI TTS devuelve 24kHz PCM
DEFAULT_MODEL = "tts-1"


class OpenAITTSBackend:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
    ):
        from openai import OpenAI
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OpenAI TTS requiere OPENAI_API_KEY (env var) o cfg.tts.openai_api_key."
            )
        self.client = OpenAI(api_key=key)
        self.model = model
        self.sample_rate = PCM_SAMPLE_RATE
        log.info("OpenAI TTS listo (model=%s, sr=%d Hz)", model, self.sample_rate)

    async def speak(
        self,
        text: str,
        voice_id: str,
        language: str = "",
        speed: float = 1.0,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> None:
        if not text.strip():
            return
        await asyncio.get_running_loop().run_in_executor(
            None, self._stream_play, text, voice_id, speed, cancel_event
        )

    def _stream_play(
        self,
        text: str,
        voice_id: str,
        speed: float,
        cancel_event: Optional[asyncio.Event],
    ) -> None:
        try:
            with self.client.audio.speech.with_streaming_response.create(
                model=self.model,
                voice=voice_id,
                input=text,
                response_format="pcm",
                speed=speed,
            ) as response:
                with sd.OutputStream(
                    samplerate=self.sample_rate, channels=1, dtype="int16",
                ) as out:
                    for chunk in response.iter_bytes(chunk_size=4096):
                        if cancel_event is not None and cancel_event.is_set():
                            return
                        if not chunk:
                            continue
                        arr = np.frombuffer(chunk, dtype=np.int16)
                        if arr.size == 0:
                            continue
                        try:
                            out.write(arr)
                        except sd.PortAudioError as e:
                            log.warning("PortAudio write falló: %s", e)
                            return
        except Exception:
            log.exception("Error sintetizando con OpenAI TTS")

    def play_demo(
        self, text: str, voice_id: str, language: str = "", speed: float = 1.0
    ) -> None:
        self._stream_play(text, voice_id, speed, None)

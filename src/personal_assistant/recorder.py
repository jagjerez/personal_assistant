"""Grabación de audio con corte automático por VAD (Voice Activity Detection)."""
import asyncio
import io
import logging
import wave
from typing import Callable, Optional

import numpy as np
import sounddevice as sd
import webrtcvad

from .config import VADConfig

log = logging.getLogger(__name__)

# webrtcvad sólo soporta frames de 10, 20 o 30 ms.
FRAME_MS = 30


async def record_until_silence(
    cfg: VADConfig,
    cancel_event: Optional[asyncio.Event] = None,
    on_level: Optional[Callable[[float], None]] = None,
) -> Optional[bytes]:
    """Graba hasta detectar `silence_duration_ms` de silencio tras haber detectado habla.

    Devuelve bytes WAV (mono, int16, 16 kHz) o None si fue cancelado o no hubo habla.
    """
    vad = webrtcvad.Vad(cfg.aggressiveness)
    frame_samples = int(cfg.sample_rate * FRAME_MS / 1000)
    silence_threshold = cfg.silence_duration_ms // FRAME_MS

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    def callback(indata, frames, time_info, status):
        if status:
            log.debug("sounddevice status: %s", status)
        pcm16 = (indata[:, 0] * 32767).astype(np.int16).tobytes()
        loop.call_soon_threadsafe(queue.put_nowait, pcm16)

    chunks: list[bytes] = []
    speech_started = False
    silence_count = 0
    elapsed_frames = 0
    max_frames = int(cfg.max_duration_s * 1000 / FRAME_MS)

    stream = sd.InputStream(
        samplerate=cfg.sample_rate,
        channels=1,
        dtype="float32",
        blocksize=frame_samples,
        callback=callback,
    )

    with stream:
        while elapsed_frames < max_frames:
            if cancel_event and cancel_event.is_set():
                log.info("Grabación cancelada por usuario")
                return None
            try:
                frame = await asyncio.wait_for(queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            chunks.append(frame)
            elapsed_frames += 1
            if on_level is not None:
                samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
                # peak con boost para visibilidad
                level = float(min(1.0, np.max(np.abs(samples)) * 2.5))
                try:
                    on_level(level)
                except Exception:
                    pass
            try:
                is_speech = vad.is_speech(frame, cfg.sample_rate)
            except Exception:
                is_speech = False
            if is_speech:
                speech_started = True
                silence_count = 0
            elif speech_started:
                silence_count += 1
                if silence_count >= silence_threshold:
                    break

    if not speech_started:
        log.info("No se detectó habla")
        return None

    pcm = b"".join(chunks)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(cfg.sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def play_beep(frequency: int = 880, duration_ms: int = 80, sample_rate: int = 22050) -> None:
    """Pitido corto para feedback de inicio/fin de grabación."""
    t = np.linspace(0, duration_ms / 1000, int(sample_rate * duration_ms / 1000), endpoint=False)
    wave_arr = 0.2 * np.sin(2 * np.pi * frequency * t)
    sd.play(wave_arr.astype(np.float32), sample_rate)
    sd.wait()

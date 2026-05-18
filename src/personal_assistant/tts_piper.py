"""Backend Piper — TTS ligero (subprocess + sounddevice)."""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd

from .voices import get_voice, piper_voice_path, download_voice

log = logging.getLogger(__name__)


class PiperBackend:
    """Una instancia compartida. La voz se resuelve por voice_id en cada speak()."""

    def __init__(self):
        self._sample_rates: dict[str, int] = {}  # cache por voz
        log.info("Piper TTS listo")

    def _resolve(self, voice_id: str) -> tuple[Path, int]:
        path = piper_voice_path(voice_id)
        if not path.exists():
            voice = get_voice(voice_id)
            if voice is None:
                raise ValueError(f"Voz desconocida: {voice_id}")
            log.info("Voz %s no descargada — bajando...", voice_id)
            download_voice(voice)
        if voice_id not in self._sample_rates:
            meta = json.loads(path.with_suffix(".onnx.json").read_text())
            self._sample_rates[voice_id] = meta["audio"]["sample_rate"]
        return path, self._sample_rates[voice_id]

    async def speak(
        self,
        text: str,
        voice_id: str,
        language: str = "",  # Piper ignora; voz lleva idioma implícito
        speed: float = 1.0,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> None:
        path, sr = self._resolve(voice_id)
        proc = await asyncio.create_subprocess_exec(
            "piper", "--model", str(path),
            "--length_scale", str(speed),
            "--output-raw",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate(text.encode("utf-8"))
        if cancel_event and cancel_event.is_set():
            return
        if not stdout:
            log.warning("Piper no produjo audio")
            return
        audio = np.frombuffer(stdout, dtype=np.int16)
        await asyncio.get_running_loop().run_in_executor(
            None, self._play, audio, sr, cancel_event
        )

    def _play(self, audio: np.ndarray, sr: int, cancel_event: Optional[asyncio.Event]) -> None:
        sd.play(audio, sr)
        try:
            while sd.get_stream().active:
                if cancel_event and cancel_event.is_set():
                    sd.stop()
                    return
                sd.sleep(100)
        except Exception:
            sd.wait()

    def play_demo(
        self, text: str, voice_id: str, language: str = "", speed: float = 1.0
    ) -> None:
        path, sr = self._resolve(voice_id)
        r = subprocess.run(
            ["piper", "--model", str(path), "--length_scale", str(speed), "--output-raw"],
            input=text.encode("utf-8"),
            capture_output=True,
        )
        if r.returncode != 0 or not r.stdout:
            log.warning("Demo Piper falló")
            return
        audio = np.frombuffer(r.stdout, dtype=np.int16)
        sd.play(audio, sr)
        sd.wait()

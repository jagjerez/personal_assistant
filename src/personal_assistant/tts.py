"""Síntesis de voz con Piper. Soporta cambio de voz sin reiniciar."""
import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd

from .config import PiperConfig

log = logging.getLogger(__name__)


class TTS:
    def __init__(self, cfg: PiperConfig):
        self.length_scale = cfg.length_scale
        self._lock = threading.Lock()
        self._load_voice(cfg.voice_path)
        self._current_proc: Optional[asyncio.subprocess.Process] = None

    def _load_voice(self, voice_path: Path) -> None:
        path = Path(voice_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(
                f"Modelo de voz no encontrado: {path}\n"
                "Ejecuta: ./scripts/install-models.sh"
            )
        meta_path = path.with_suffix(".onnx.json")
        if not meta_path.exists():
            meta_path = Path(f"{path}.json")
        meta = json.loads(meta_path.read_text())
        with self._lock:
            self.voice_path = path
            self.sample_rate = meta["audio"]["sample_rate"]
        log.info("TTS Piper listo: %s (%d Hz)", path.name, self.sample_rate)

    def set_voice(self, voice_path: Path) -> None:
        """Cambia la voz en caliente. Si Piper está reproduciendo, terminará la frase actual."""
        self._load_voice(voice_path)

    async def speak(self, text: str, cancel_event: Optional[asyncio.Event] = None) -> None:
        if not text.strip():
            return
        with self._lock:
            voice = str(self.voice_path)
            sample_rate = self.sample_rate

        proc = await asyncio.create_subprocess_exec(
            "piper", "--model", voice,
            "--length_scale", str(self.length_scale),
            "--output-raw",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._current_proc = proc
        try:
            stdout, _ = await proc.communicate(text.encode("utf-8"))
        finally:
            self._current_proc = None

        if cancel_event and cancel_event.is_set():
            return
        if not stdout:
            log.warning("Piper no produjo audio para: %r", text[:60])
            return

        audio = np.frombuffer(stdout, dtype=np.int16)
        await asyncio.get_running_loop().run_in_executor(
            None, self._play, audio, sample_rate, cancel_event
        )

    def _play(self, audio: np.ndarray, sample_rate: int,
              cancel_event: Optional[asyncio.Event]) -> None:
        sd.play(audio, sample_rate)
        try:
            while sd.get_stream().active:
                if cancel_event and cancel_event.is_set():
                    sd.stop()
                    return
                sd.sleep(100)
        except Exception:
            sd.wait()

    def play_demo(self, text: str, voice_path: Path) -> None:
        """Reproduce un demo síncrono con una voz arbitraria. Usado por el menú."""
        import subprocess
        path = Path(voice_path).expanduser()
        meta_path = path.with_suffix(".onnx.json")
        if not meta_path.exists():
            meta_path = Path(f"{path}.json")
        meta = json.loads(meta_path.read_text())
        sr = meta["audio"]["sample_rate"]
        result = subprocess.run(
            ["piper", "--model", str(path), "--length_scale", str(self.length_scale),
             "--output-raw"],
            input=text.encode("utf-8"),
            capture_output=True,
        )
        if result.returncode != 0:
            log.warning("Piper demo falló: %s", result.stderr.decode()[:200])
            return
        audio = np.frombuffer(result.stdout, dtype=np.int16)
        sd.play(audio, sr)
        sd.wait()

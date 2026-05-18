from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator


def _expand(p: str | Path) -> Path:
    return Path(p).expanduser().resolve()


class HotkeyConfig(BaseModel):
    modifier: str = "LEFTMETA"
    key: str = "X"
    device: Optional[str] = None


class WhisperConfig(BaseModel):
    model: str = "medium"
    language: str = "es"
    device: str = "cpu"           # cpu | cuda | auto
    compute_type: str = "int8"     # int8 (cpu), float16 (gpu), float32


class TTSConfig(BaseModel):
    """Configuración del motor de TTS (engine-agnostic)."""
    engine: str = "xtts"        # "xtts" | "piper"
    voice: str = "Ana Florence"  # ID del catálogo voices.py
    device: str = "cuda"         # cuda | cpu (sólo relevante para xtts)
    speed: float = 1.0           # 1.0 normal, <1 más rápido, >1 más lento


class VADConfig(BaseModel):
    aggressiveness: int = Field(2, ge=0, le=3)
    silence_duration_ms: int = 1500
    sample_rate: int = 16000
    max_duration_s: float = 30.0


class ClaudeConfig(BaseModel):
    command: str = "claude"
    context_threshold: float = Field(0.75, gt=0, le=1)
    max_context_tokens: int = 200_000
    model: Optional[str] = None
    # Si True, lanza Claude con --dangerously-skip-permissions. Permite a Claude
    # ejecutar comandos, editar ficheros, etc. SIN preguntar. Necesario para
    # control por voz, pero implica que cualquier voz interpretada como
    # instrucción destructiva se ejecuta. ÚSALO BAJO TU RIESGO.
    dangerously_skip_permissions: bool = False
    # Idioma de respuesta del asistente (afecta también a Whisper STT)
    language: str = "es"


class PathsConfig(BaseModel):
    personality_file: Path
    memory_file: Path
    log_dir: Path
    session_dir: Path

    @field_validator("*", mode="before")
    @classmethod
    def _expand_all(cls, v):
        return _expand(v)


class AudioConfig(BaseModel):
    beep: bool = True


class OverlayConfig(BaseModel):
    enabled: bool = True
    margin_bottom: int = 60
    width: int = 320
    height: int = 70
    opacity: float = Field(0.92, ge=0.0, le=1.0)


class Config(BaseModel):
    hotkey: HotkeyConfig = HotkeyConfig()
    whisper: WhisperConfig = WhisperConfig()
    tts: TTSConfig = TTSConfig()
    vad: VADConfig = VADConfig()
    claude: ClaudeConfig = ClaudeConfig()
    paths: PathsConfig
    audio: AudioConfig = AudioConfig()
    overlay: OverlayConfig = OverlayConfig()

    @classmethod
    def load(cls, path: Path) -> "Config":
        if not path.exists():
            raise FileNotFoundError(
                f"No existe {path}. Copia config/config.example.yaml a "
                f"~/.config/personal-assistant/config.yaml y edítalo."
            )
        data = yaml.safe_load(path.read_text()) or {}
        return cls(**data)


def default_config_path() -> Path:
    return _expand("~/.config/personal-assistant/config.yaml")

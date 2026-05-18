"""Entry point: `assistant` o `python -m personal_assistant`.

Arquitectura: Qt corre en el thread principal (necesario para widgets).
El daemon asyncio corre en un thread de fondo. Se comunican vía Qt Signals.
"""
import argparse
import asyncio
import logging
import os
import signal
import sys
import threading
from pathlib import Path

# Wayland (GNOME, KDE, ...) NO permite a los clientes posicionar sus ventanas ni
# forzar always-on-top — limitación de seguridad. Forzamos XWayland para que Qt
# use el protocolo X11 a través de la capa de traducción de Wayland (siempre
# disponible en sesiones Wayland modernas). Resultado: el overlay aparece
# exactamente donde lo pedimos y sobre todas las ventanas.
if os.environ.get("XDG_SESSION_TYPE") == "wayland":
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

# Acepta la licencia CPML de XTTS-v2 sin prompt interactivo.
os.environ.setdefault("COQUI_TOS_AGREED", "1")

# Silencia warnings ruidosos de Qt (antes del primer import de PySide6).
os.environ.setdefault(
    "QT_LOGGING_RULES",
    "qt.qpa.theme.*=false;qt.qpa.wayland.*=false;qt.qpa.xcb.*=false",
)

# Preload CUDA libs si están disponibles (antes de faster_whisper / ctranslate2).
from ._cuda import preload_nvidia_libs  # noqa: E402
preload_nvidia_libs()

from .config import Config, default_config_path  # noqa: E402
from .daemon import Daemon  # noqa: E402


def _setup_logging(log_dir: Path, verbose: bool) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(log_dir / "assistant.log"),
    ]
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    for noisy in (
        "faster_whisper", "httpx", "httpcore", "httpcore.http11", "httpcore.connection",
        "urllib3", "filelock", "huggingface_hub", "hf_hub", "asyncio",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _save_config(cfg_path: Path, language: str, voice_id: str) -> None:
    """Persiste idioma + voz seleccionados en config.yaml."""
    import yaml
    from .voices import get_voice
    voice = get_voice(voice_id)
    data = yaml.safe_load(cfg_path.read_text()) or {}
    data.setdefault("whisper", {})["language"] = language
    data.setdefault("claude", {})["language"] = language
    tts = data.setdefault("tts", {})
    tts["voice"] = voice_id
    if voice is not None:
        tts["engine"] = voice.engine
    cfg_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


def _run_daemon_thread(daemon: Daemon, on_exit) -> threading.Thread:
    def target() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(daemon.run())
        except Exception:
            logging.getLogger(__name__).exception("Daemon crash")
        finally:
            loop.close()
            on_exit()

    t = threading.Thread(target=target, name="daemon", daemon=True)
    t.start()
    return t


def cli() -> None:
    parser = argparse.ArgumentParser(prog="assistant")
    parser.add_argument("-c", "--config", type=Path, default=default_config_path())
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--no-overlay", action="store_true",
                        help="Arrancar sin overlay flotante (modo headless)")
    args = parser.parse_args()

    try:
        cfg = Config.load(args.config)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    _setup_logging(cfg.paths.log_dir, args.verbose)
    log = logging.getLogger("personal_assistant")

    use_overlay = cfg.overlay.enabled and not args.no_overlay

    if use_overlay:
        from .indicator import Overlay, create_app
        from .menu import SettingsDialog

        app = create_app()
        overlay = Overlay(cfg.overlay)

        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

        daemon = Daemon(cfg, indicator=overlay)
        current_voice_id = cfg.tts.voice

        def open_settings():
            def play_demo(text: str, voice_id: str) -> None:
                daemon.tts.play_demo(text, voice_id, language=cfg.claude.language)

            def on_save(language: str, voice_id: str) -> None:
                _save_config(args.config, language, voice_id)
                daemon.apply_language(language)
                daemon.apply_voice(voice_id)
                nonlocal current_voice_id
                current_voice_id = voice_id

            dialog = SettingsDialog(
                current_language=cfg.claude.language,
                current_voice_id=current_voice_id,
                play_demo=play_demo,
                on_save=on_save,
                parent=overlay,
            )
            dialog.exec()

        overlay.sig_menu_requested.connect(open_settings)

        def on_daemon_exit() -> None:
            log.info("Daemon terminó. Cerrando app.")
            app.quit()

        _run_daemon_thread(daemon, on_daemon_exit)
        log.info("Overlay listo. (Ctrl+C para salir)")
        sys.exit(app.exec())
    else:
        daemon = Daemon(cfg)

        async def main() -> None:
            loop = asyncio.get_running_loop()
            stop = asyncio.Event()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, stop.set)
            run_task = asyncio.create_task(daemon.run())
            stop_task = asyncio.create_task(stop.wait())
            _, pending = await asyncio.wait(
                {run_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
            log.info("Apagando")

        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    cli()

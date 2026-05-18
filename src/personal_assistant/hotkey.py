"""Escucha de hotkey global en Wayland vía evdev.

Funcionamiento: lee /dev/input/event* en paralelo para todos los teclados,
emite un evento cuando se detecta <modifier>+<key> (key down).
Requiere que el usuario esté en el grupo `input`.
"""
import asyncio
import glob
import logging
from typing import AsyncIterator, Optional

from evdev import InputDevice, ecodes

from .config import HotkeyConfig

log = logging.getLogger(__name__)


def _key_code(name: str) -> int:
    full = f"KEY_{name.upper()}"
    code = getattr(ecodes, full, None)
    if code is None:
        raise ValueError(f"Tecla desconocida: {name} (probado {full})")
    return code


def _find_keyboards(
    explicit_device: Optional[str], required_keys: tuple[int, ...]
) -> list[InputDevice]:
    if explicit_device:
        return [InputDevice(explicit_device)]

    # Usamos glob directo (NO evdev.list_devices, que filtra silenciosamente
    # los que no podemos abrir y oculta el problema de permisos).
    all_paths = sorted(glob.glob("/dev/input/event*"))
    if not all_paths:
        raise RuntimeError("No hay dispositivos en /dev/input/event*. ¿Kernel sin evdev?")

    devices: list[InputDevice] = []
    perm_denied: list[str] = []
    other_errors: list[tuple[str, str]] = []

    for path in all_paths:
        try:
            dev = InputDevice(path)
        except PermissionError:
            perm_denied.append(path)
            continue
        except OSError as e:
            other_errors.append((path, str(e)))
            continue
        caps = dev.capabilities()
        keys = caps.get(ecodes.EV_KEY, [])
        # Un teclado útil debe poder emitir las teclas que necesitamos.
        if all(k in keys for k in required_keys):
            log.info("Teclado detectado: %s (%s)", path, dev.name)
            devices.append(dev)
        else:
            dev.close()

    if devices:
        return devices

    # No se encontró nada. Diagnóstico detallado.
    msg = [f"No se encontró ningún teclado capaz de emitir las teclas configuradas."]
    msg.append(f"Examinados: {len(all_paths)} dispositivos en /dev/input/")
    msg.append(f"  ✓ Accesibles: {len(all_paths) - len(perm_denied) - len(other_errors)}")
    msg.append(f"  ✗ Sin permisos: {len(perm_denied)}")
    if other_errors:
        msg.append(f"  ✗ Otros errores: {len(other_errors)}")
    if perm_denied:
        msg.append("")
        msg.append("→ No estás en el grupo 'input'. Arreglo:")
        msg.append("  1. sudo usermod -aG input $USER")
        msg.append("  2. cierra sesión gráfica y vuelve a entrar")
        msg.append("     (o atajo: `newgrp input` y lanza el assistant desde esa sub-shell)")
    else:
        msg.append("")
        msg.append("→ Permisos OK pero ningún dispositivo tiene las teclas requeridas.")
        msg.append("  Fija 'hotkey.device' en config.yaml apuntando al evento de tu teclado.")
    raise RuntimeError("\n".join(msg))


async def hotkey_events(cfg: HotkeyConfig) -> AsyncIterator[None]:
    """Itera emitiendo None cada vez que se pulsa <modifier>+<key>."""
    modifier_code = _key_code(cfg.modifier)
    key_code = _key_code(cfg.key)

    devices = _find_keyboards(cfg.device, required_keys=(modifier_code, key_code))
    log.info("Escuchando hotkey en %d teclado(s): %s",
             len(devices), [d.path for d in devices])

    queue: asyncio.Queue[None] = asyncio.Queue()

    async def watch(dev: InputDevice) -> None:
        modifier_held = False
        try:
            async for ev in dev.async_read_loop():
                if ev.type != ecodes.EV_KEY:
                    continue
                if ev.code == modifier_code:
                    modifier_held = (ev.value in (1, 2))  # press o repeat
                elif ev.code == key_code and ev.value == 1 and modifier_held:
                    await queue.put(None)
        except OSError as e:
            log.warning("Dispositivo %s desconectado: %s", dev.path, e)

    tasks = [asyncio.create_task(watch(d)) for d in devices]
    try:
        while True:
            await queue.get()
            yield
    finally:
        for t in tasks:
            t.cancel()
        for d in devices:
            d.close()

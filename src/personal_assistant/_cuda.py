"""Preload de libs CUDA desde wheels nvidia-*.

ctranslate2 (motor de faster-whisper) busca libcublas/libcudnn por nombre vía
dlopen. Las wheels nvidia-cublas-cu12 y nvidia-cudnn-cu12 las dejan dentro del
venv (site-packages/nvidia/{cublas,cudnn}/lib/), que no está en LD_LIBRARY_PATH.
Las cargamos con RTLD_GLOBAL para que estén en el process address space cuando
ctranslate2 las pida.

DEBE invocarse ANTES de importar faster_whisper / ctranslate2.
"""
import ctypes
import glob
import logging
import os
import sys

log = logging.getLogger(__name__)


def preload_nvidia_libs() -> bool:
    """Devuelve True si encontró y precargó libs CUDA, False si no había."""
    venv = sys.prefix
    lib_dirs: list[str] = []
    for sub in ("cublas", "cudnn", "cuda_nvrtc", "cuda_runtime"):
        matches = glob.glob(f"{venv}/lib/python*/site-packages/nvidia/{sub}/lib")
        if matches:
            lib_dirs.append(matches[0])

    if not lib_dirs:
        log.debug("No se encontraron wheels nvidia-*. CUDA no disponible vía pip.")
        return False

    # Añadir a LD_LIBRARY_PATH (para subprocesos que se lancen después).
    ld = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = ":".join(lib_dirs + ([ld] if ld else []))

    # Cargar las .so con RTLD_GLOBAL — orden importa: cublas/nvrtc primero,
    # luego cudnn (que depende de cublas).
    loaded = 0
    for sub in ("cuda_nvrtc", "cuda_runtime", "cublas", "cudnn"):
        for d in lib_dirs:
            if not d.endswith(f"/{sub}/lib"):
                continue
            for so in sorted(glob.glob(f"{d}/*.so*")):
                try:
                    ctypes.CDLL(so, mode=ctypes.RTLD_GLOBAL)
                    loaded += 1
                except OSError as e:
                    log.debug("No se pudo precargar %s: %s", so, e)
    log.debug("CUDA libs precargadas: %d en %d directorios", loaded, len(lib_dirs))
    return loaded > 0

# Personal Assistant

Asistente personal por voz para Linux. Pulsas `Super+X`, hablas, te responde con voz tras procesar la entrada con Claude Code. Personalidad, memoria persistente, idioma y voz configurables.

## Características

- **Push-to-talk con VAD**: `Super+X` empieza a grabar, corta solo tras 1.5s de silencio.
- **STT local**: faster-whisper con soporte CPU y GPU NVIDIA.
- **LLM**: Claude Code en sesión persistente con rotación automática al llenarse el contexto.
- **TTS local**: Piper con catálogo de voces masculinas y femeninas en español e inglés.
- **Overlay flotante**: barra horizontal en parte inferior central de la pantalla, siempre visible, con animaciones morfantes (idle → mic → thinking → wave → idle).
- **Menú in-app**: clic en la barra abre selector de idioma y voz con demos.
- **Memoria persistente**: el asistente lee y escribe `memory.md`, no pierde contexto entre sesiones.
- **Modo control de PC**: opción `dangerously_skip_permissions` para que Claude ejecute comandos a través de voz.

## Instalación rápida

```bash
git clone git@github.com:jagjerez/personal_assistant.git
cd personal_assistant
./scripts/install.sh
```

El instalador hace lo siguiente, en orden:
1. Verifica dependencias apt (`portaudio19-dev`, `ffmpeg`, `curl`).
2. Comprueba que tu usuario está en el grupo `input` (necesario para hotkey en Wayland).
3. Instala `uv`, crea venv con Python 3.12.
4. Instala el paquete con sus deps.
5. Detecta GPU NVIDIA y ofrece instalar libs CUDA.
6. Copia config inicial a `~/.config/personal-assistant/`.
7. Descarga la voz por defecto (sharvard, mujer ES).
8. Crea servicio systemd user y opcionalmente activa autostart.

Si te pide un paso manual (apt, usermod) hazlo y relanza el script. Es idempotente.

## Uso

```bash
assistant            # lanza con overlay
assistant -v         # logs verbosos
assistant --no-overlay   # modo headless
```

- **Super+X**: empieza/cancela grabación.
- **Clic en la barra**: abre menú de idioma y voz.
- **Ctrl+C** en el terminal del daemon: salir.

## Servicio systemd (autostart)

Si lo activaste en el instalador, ya está corriendo. Comandos útiles:

```bash
systemctl --user status personal-assistant     # estado
systemctl --user restart personal-assistant    # reinicia
systemctl --user stop personal-assistant       # parar
systemctl --user disable personal-assistant    # desactivar autostart
journalctl --user -u personal-assistant -f     # logs en vivo
```

## Configuración

Archivos en `~/.config/personal-assistant/`:

- **`config.yaml`**: hotkey, VAD, modelos, GPU, paths, modo permisos. Comentado en el archivo.
- **`personality.md`**: cómo debe responder el asistente. Edítalo libremente.
- **`memory.md`**: memoria persistente. El asistente la lee al arrancar y escribe en ella al rotar sesión.

### Cambiar voz o idioma sin reiniciar
Clic en la barra flotante → diálogo. Elige idioma, escucha demos, guarda. Cambia en caliente.

### Activar control de PC por voz

En `config.yaml` → `claude.dangerously_skip_permissions: true`. Claude podrá ejecutar comandos sin confirmar. **Úsalo bajo tu propio riesgo**: cualquier voz interpretada como instrucción destructiva se ejecutará. Mitigado parcialmente por el hecho de que el micro solo escucha cuando pulsas `Super+X`.

### GPU NVIDIA

Para usar GPU NVIDIA con Whisper:

```bash
source .venv/bin/activate
uv pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9.0,<10"
```

En `config.yaml` → `whisper.device: cuda`. `compute_type` según GPU:
- `int8` para Pascal (GTX 10xx, sin tensor cores).
- `int8_float16` para Turing+ (RTX 20xx en adelante).
- `float16` para Ampere/Ada (RTX 30xx/40xx).

## Stack

| Capa | Tecnología |
|---|---|
| Hotkey global Wayland | evdev (lectura directa de `/dev/input/event*`) |
| Captura audio | sounddevice + webrtcvad |
| STT | faster-whisper (medium ES por defecto) |
| LLM | Claude Code CLI, sesión persistente con UUID + `--resume` |
| TTS | Piper (subprocess) |
| Overlay/Menú | PySide6 con QPainter custom |
| Threading | Qt en main thread, daemon asyncio en thread aparte, signals cross-thread |

## Solución de problemas

| Síntoma | Causa | Solución |
|---|---|---|
| `No se encontró ningún teclado` | Usuario no en grupo `input` | `sudo usermod -aG input $USER` + relogin |
| `libcublas.so.12 not found` | CUDA libs no instaladas | `uv pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` o `device: cpu` |
| `Requested float16 compute type...` | GPU sin tensor cores | Cambiar `compute_type` a `int8` |
| Overlay no aparece | Compositor Wayland ignorando posición | Probar en otro compositor o ajustar `margin_bottom` |
| Voz robótica | sample rate mal detectado | Ver logs verbosos |

## Licencia

Personal. Úsalo, modifícalo, comparte si quieres.

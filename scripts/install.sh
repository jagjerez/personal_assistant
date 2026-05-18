#!/usr/bin/env bash
# Instalador end-to-end del asistente personal por voz.
# Idempotente: puedes relanzarlo sin miedo.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="${HOME}/.config/personal-assistant"
SYSTEMD_DIR="${HOME}/.config/systemd/user"

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
ok()   { printf "  ✓ %s\n" "$*"; }
warn() { printf "  ⚠ %s\n" "$*"; }
err()  { printf "  ✗ %s\n" "$*" >&2; }

bold "── Personal Assistant — Instalador ──"
echo

# 1) Comprobar dependencias del sistema
bold "[1/6] Dependencias del sistema"
NEEDED_APT=()
for pkg in portaudio19-dev ffmpeg curl; do
  if ! dpkg -s "$pkg" >/dev/null 2>&1; then
    NEEDED_APT+=("$pkg")
  fi
done
if (( ${#NEEDED_APT[@]} > 0 )); then
  warn "Faltan paquetes apt: ${NEEDED_APT[*]}"
  echo "  Ejecuta:"
  echo "    sudo apt install -y ${NEEDED_APT[*]}"
  echo "  Luego relanza este script."
  exit 1
fi
ok "Paquetes apt presentes"

# 2) Grupo input
bold "[2/6] Grupo 'input' (hotkey global en Wayland)"
if groups | grep -qw input; then
  ok "Ya en el grupo input"
else
  warn "Tu usuario NO está en el grupo input"
  echo "  Ejecuta:"
  echo "    sudo usermod -aG input \$USER"
  echo "    # luego cierra sesión gráfica y vuelve a entrar"
  echo "  Después relanza este script."
  exit 1
fi

# 3) uv + venv
bold "[3/6] Python 3.12 y venv (vía uv)"
if ! command -v uv >/dev/null 2>&1; then
  echo "  Instalando uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # asegurar PATH para esta sesión
  export PATH="${HOME}/.local/bin:${PATH}"
fi
ok "uv disponible"

cd "${PROJECT_DIR}"
if [[ ! -d .venv ]]; then
  uv venv --python 3.12
fi
ok "venv creado"

# 4) Dependencias Python
bold "[4/6] Dependencias Python"
uv pip install -e . >/dev/null
ok "Paquete personal-assistant instalado"

# Detectar GPU NVIDIA y ofrecer CUDA
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L | grep -q GPU; then
  echo "  GPU NVIDIA detectada:"
  nvidia-smi -L | sed 's/^/    /'
  read -rp "  ¿Instalar libs CUDA para acelerar Whisper? [Y/n] " ans
  ans=${ans:-Y}
  if [[ "$ans" =~ ^[Yy]$ ]]; then
    uv pip install "nvidia-cublas-cu12" "nvidia-cudnn-cu12>=9.0,<10" >/dev/null
    ok "Libs CUDA instaladas"
  fi
fi

# 5) Configuración usuario
bold "[5/6] Configuración"
mkdir -p "${CONFIG_DIR}"
if [[ ! -f "${CONFIG_DIR}/config.yaml" ]]; then
  cp "${PROJECT_DIR}/config/config.example.yaml" "${CONFIG_DIR}/config.yaml"
  ok "config.yaml creado en ${CONFIG_DIR}"
else
  ok "config.yaml ya existía (no se sobrescribe)"
fi
if [[ ! -f "${CONFIG_DIR}/personality.md" ]]; then
  cp "${PROJECT_DIR}/config/personality.example.md" "${CONFIG_DIR}/personality.md"
  ok "personality.md creado"
else
  ok "personality.md ya existía"
fi

bash "${PROJECT_DIR}/scripts/install-models.sh"

# 6) systemd user service (autostart)
bold "[6/6] Servicio systemd (autostart al iniciar sesión)"
mkdir -p "${SYSTEMD_DIR}"
SERVICE_SRC="${PROJECT_DIR}/systemd/personal-assistant.service"
SERVICE_DST="${SYSTEMD_DIR}/personal-assistant.service"
# Re-genera con la ruta correcta del venv
sed "s|__VENV_BIN__|${PROJECT_DIR}/.venv/bin|g" "${SERVICE_SRC}" > "${SERVICE_DST}"
ok "Servicio instalado en ${SERVICE_DST}"

systemctl --user daemon-reload

read -rp "  ¿Activar autostart al iniciar sesión gráfica? [Y/n] " ans
ans=${ans:-Y}
if [[ "$ans" =~ ^[Yy]$ ]]; then
  systemctl --user enable personal-assistant.service
  ok "Autostart activado (se lanzará al iniciar sesión)"
  read -rp "  ¿Arrancar ahora? [Y/n] " ans2
  ans2=${ans2:-Y}
  if [[ "$ans2" =~ ^[Yy]$ ]]; then
    systemctl --user restart personal-assistant.service
    ok "Asistente en marcha"
    echo
    echo "  Logs en tiempo real:"
    echo "    journalctl --user -u personal-assistant -f"
  fi
else
  echo "  Para arrancar manualmente:"
  echo "    source ${PROJECT_DIR}/.venv/bin/activate && assistant -v"
fi

echo
bold "Instalación completa."
echo "Atajo: Super+X para hablar. Click en la barra → menú de voz/idioma."

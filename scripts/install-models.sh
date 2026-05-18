#!/usr/bin/env bash
# Descarga la voz Piper por defecto (mujer ES).
# Las demás voces se descargan on-demand desde el menú de configuración.
set -euo pipefail

VOICE_DIR="${HOME}/.local/share/personal-assistant/voices"
HF_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main"

declare -A VOICES=(
  ["es_ES-sharvard-medium"]="es/es_ES/sharvard/medium"
)

mkdir -p "${VOICE_DIR}"

for VOICE in "${!VOICES[@]}"; do
  REL_PATH="${VOICES[$VOICE]}"
  ONNX="${VOICE_DIR}/${VOICE}.onnx"
  JSON="${VOICE_DIR}/${VOICE}.onnx.json"

  echo "→ Voz: ${VOICE}"
  if [[ ! -f "${ONNX}" ]]; then
    curl -L --fail -o "${ONNX}"  "${HF_BASE}/${REL_PATH}/${VOICE}.onnx"
    curl -L --fail -o "${JSON}"  "${HF_BASE}/${REL_PATH}/${VOICE}.onnx.json"
    echo "  ✓ Instalada en ${VOICE_DIR}"
  else
    echo "  ✓ Ya existía"
  fi
done

echo
echo "Listo. El resto de voces se descargan desde el menú del asistente"
echo "(clic en la barra flotante → ▶ junto a la voz que quieras probar)."

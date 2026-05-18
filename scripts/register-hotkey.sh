#!/usr/bin/env bash
# Registra Super+X como atajo custom de GNOME para que el evento sea CONSUMIDO
# por GNOME (las apps NO lo reciben), pero nuestro daemon SÍ lo ve porque lee
# /dev/input/event* a nivel kernel — antes que la cadena de eventos de GNOME.
#
# El "comando" del atajo es un no-op (`true`) — sólo nos interesa el efecto
# secundario: GNOME se traga la tecla.
#
# Uso:
#   ./scripts/register-hotkey.sh         # registra
#   ./scripts/register-hotkey.sh --remove # elimina
set -euo pipefail

SCHEMA="org.gnome.settings-daemon.plugins.media-keys"
PATH_PREFIX="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
ENTRY_PATH="${PATH_PREFIX}/personal-assistant/"
KEY_BINDING="<Super>x"
NAME="Personal Assistant"
COMMAND="true"

if ! command -v gsettings >/dev/null 2>&1; then
  echo "Error: gsettings no disponible (¿no es GNOME?)" >&2
  exit 1
fi

current_list() {
  gsettings get "${SCHEMA}" custom-keybindings 2>/dev/null || echo "@as []"
}

add_to_list() {
  local list="$1"
  if [[ "${list}" == "@as []" || "${list}" == "[]" ]]; then
    echo "['${ENTRY_PATH}']"
  elif [[ "${list}" == *"${ENTRY_PATH}"* ]]; then
    echo "${list}"
  else
    # Inserta antes del cierre del array
    echo "${list%]*}, '${ENTRY_PATH}']"
  fi
}

remove_from_list() {
  local list="$1"
  list="${list//, '${ENTRY_PATH}'/}"
  list="${list//'${ENTRY_PATH}', /}"
  list="${list//'${ENTRY_PATH}'/}"
  list="${list//[ ]/}"
  if [[ "${list}" == "[]" ]]; then
    echo "@as []"
  else
    echo "${list}"
  fi
}

if [[ "${1:-}" == "--remove" ]]; then
  CURRENT=$(current_list)
  NEW=$(remove_from_list "${CURRENT}")
  gsettings set "${SCHEMA}" custom-keybindings "${NEW}"
  echo "✓ Atajo eliminado. Super+X vuelve a propagarse a las apps."
  exit 0
fi

# Registrar
CURRENT=$(current_list)
NEW=$(add_to_list "${CURRENT}")
gsettings set "${SCHEMA}" custom-keybindings "${NEW}"

KEYBIND_SCHEMA="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
gsettings set "${KEYBIND_SCHEMA}:${ENTRY_PATH}" name    "${NAME}"
gsettings set "${KEYBIND_SCHEMA}:${ENTRY_PATH}" command "${COMMAND}"
gsettings set "${KEYBIND_SCHEMA}:${ENTRY_PATH}" binding "${KEY_BINDING}"

echo "✓ Atajo registrado: ${KEY_BINDING}"
echo "  GNOME ahora se traga la combinación, las apps NO la verán."
echo "  El daemon SÍ la sigue viendo (lee /dev/input/event* a nivel kernel)."
echo
echo "Para revertir: ./scripts/register-hotkey.sh --remove"

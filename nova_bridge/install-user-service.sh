#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/universal-dragon-voice-core"
BRIDGE_DIR="${ROOT}/nova_bridge"
CFG_DIR="${HOME}/.config/universal-dragon"
CFG_FILE="${CFG_DIR}/nova-bridge.env"
UNIT_DIR="${HOME}/.config/systemd/user"
UNIT_FILE="${UNIT_DIR}/nova-bridge.service"

if [[ ! -d "${BRIDGE_DIR}" ]]; then
  echo "ERROR: expected repo at ${ROOT}"
  echo "Clone/pull the nova-voice-soul-v3 branch first."
  exit 1
fi

command -v python3 >/dev/null || { echo "ERROR: python3 not found"; exit 1; }
command -v systemctl >/dev/null || { echo "ERROR: systemctl not found"; exit 1; }

mkdir -p "${CFG_DIR}" "${UNIT_DIR}" "${BRIDGE_DIR}/runtime_audio"
chmod 700 "${BRIDGE_DIR}/runtime_audio"

if [[ ! -f "${CFG_FILE}" ]]; then
  cp "${BRIDGE_DIR}/nova-bridge.env.example" "${CFG_FILE}"
  chmod 600 "${CFG_FILE}"
  echo "Created ${CFG_FILE} (edit secrets locally before starting)."
else
  chmod 600 "${CFG_FILE}"
  echo "Keeping existing ${CFG_FILE}."
fi

python3 -m venv "${BRIDGE_DIR}/.venv"
"${BRIDGE_DIR}/.venv/bin/python3" -m pip install --upgrade pip
"${BRIDGE_DIR}/.venv/bin/pip" install -r "${BRIDGE_DIR}/requirements.txt"

cp "${BRIDGE_DIR}/nova-bridge.service" "${UNIT_FILE}"
systemctl --user daemon-reload

echo
echo "NOVA Bridge installed but not started automatically."
echo "1) Edit: ${CFG_FILE}"
echo "2) Run:  ${BRIDGE_DIR}/check-config.sh"
echo "3) Then: systemctl --user enable --now nova-bridge.service"
echo "4) Test: curl http://127.0.0.1:8130/healthz"

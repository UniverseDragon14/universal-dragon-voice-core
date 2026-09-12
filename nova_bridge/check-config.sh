#!/usr/bin/env bash
set -euo pipefail

CFG="${HOME}/.config/universal-dragon/nova-bridge.env"

if [[ ! -f "${CFG}" ]]; then
  echo "ERROR: missing ${CFG}"
  exit 1
fi

# Read only variable names/values needed for validation. Never print secret values.
set -a
# shellcheck disable=SC1090
source "${CFG}"
set +a

fail=0

check_secret() {
  local name="$1"
  local value="${!name:-}"
  if [[ -n "${value}" && "${value}" == CHANGE_ME* ]]; then
    echo "ERROR: ${name} still contains a placeholder."
    fail=1
  fi
}

check_secret NOVA_BRIDGE_TOKEN
check_secret NOVA_VOICE_TOKEN

if [[ -z "${GROQ_API_KEY:-}" && -z "${MOONSHOT_API_KEY:-}" && -z "${OPENAI_API_KEY:-}" ]]; then
  echo "ERROR: configure at least one brain provider key."
  fail=1
fi

if [[ "${NOVA_BRIDGE_HOST:-127.0.0.1}" != "127.0.0.1" ]]; then
  echo "WARN: NOVA_BRIDGE_HOST is not 127.0.0.1; localhost bind is recommended behind the tunnel."
fi

origins="${NOVA_ALLOWED_ORIGINS:-}"
if [[ "${origins}" != *"https://voice.universaldragon.com"* && "${origins}" != *"https://project28268.websitepublisher.ai"* ]]; then
  echo "WARN: expected website origin is not present in NOVA_ALLOWED_ORIGINS."
fi

if [[ "${NOVA_REQUIRE_CF_ACCESS:-1}" == "1" ]]; then
  echo "OK: Cloudflare Access requirement is enabled."
else
  echo "WARN: Cloudflare Access requirement is disabled; use only for local testing."
fi

if [[ "${fail}" -ne 0 ]]; then
  echo "Config check FAILED. No service changes were made."
  exit 1
fi

echo "Config check PASS. Secrets were not displayed."

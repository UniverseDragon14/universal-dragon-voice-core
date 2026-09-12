#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("NOVA_BRIDGE_TEST_URL", "http://127.0.0.1:8130").rstrip("/")
TOKEN = os.environ.get("NOVA_BRIDGE_TOKEN", "").strip()


def fetch_json(path: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    body = None
    headers = {"Accept": "application/json", "Origin": "https://project28268.websitepublisher.ai"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    try:
        health = fetch_json("/healthz")
    except Exception as exc:
        print(f"FAIL health: {exc.__class__.__name__}: {exc}")
        return 1

    if not health.get("ok") or health.get("executes_actions") is not False:
        print("FAIL health boundary")
        return 1
    print("PASS health: conversation-only bridge is reachable")

    try:
        chat = fetch_json(
            "/v1/chat",
            method="POST",
            payload={
                "text": "NOVA, reply with a short hello for a bridge smoke test.",
                "session_id": "smoketest01",
                "language": "en",
                "mood": "warm",
            },
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"FAIL chat HTTP {exc.code}: {detail[:300]}")
        return 1
    except Exception as exc:
        print(f"FAIL chat: {exc.__class__.__name__}: {exc}")
        return 1

    if not chat.get("ok"):
        print("FAIL chat returned ok=false")
        return 1
    if chat.get("executed_action") is not False:
        print("FAIL safety boundary: executed_action must be false")
        return 1
    if not str(chat.get("reply", "")).strip():
        print("FAIL empty reply")
        return 1

    print(f"PASS brain: {chat.get('brain', 'unknown')}")
    voice = chat.get("voice") or {}
    if chat.get("audio_url"):
        print(
            "PASS voice: "
            + ", ".join(
                f"{k}={voice.get(k, 'unknown')}" for k in ("engine", "language", "mood")
            )
        )
    else:
        print(f"WARN voice unavailable: {voice.get('status', 'unknown')} (text reply still works)")

    print("PASS NOVA bridge smoke test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

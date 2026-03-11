"""T026: End-to-end validation of Copilot SDK integration.

Tests all contract shapes from specs/005-copilot-sdk-chat/contracts/websocket-events.md
without requiring a live GitHub Copilot subscription.

Run: .venv/bin/python3.12 scripts/validate_copilot_t026.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8420"
PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  {PASS} {label}")
    else:
        print(f"  {FAIL} {label}{': ' + detail if detail else ''}")
        failures.append(f"{label}{': ' + detail if detail else ''}")


# ── helpers ───────────────────────────────────────────────────────────────────


def get_json(path: str) -> dict:
    url = BASE + path
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


# ── 1. REST: /api/copilot/status ─────────────────────────────────────────────


def validate_status() -> None:
    print("\n[1] GET /api/copilot/status")
    data = get_json("/api/copilot/status")
    print(f"    response: {json.dumps(data)}")

    required_keys = {"connected", "auth_ok", "sdk_state", "byok_mode", "active_sessions"}
    check("has all required keys", required_keys <= data.keys(),
          f"missing: {required_keys - data.keys()}")
    check("connected is bool", isinstance(data.get("connected"), bool))
    check("auth_ok is bool", isinstance(data.get("auth_ok"), bool))
    check("sdk_state is str", isinstance(data.get("sdk_state"), str))
    check("byok_mode is bool", isinstance(data.get("byok_mode"), bool))
    check("active_sessions is int", isinstance(data.get("active_sessions"), int))
    # token must not appear
    check("github_token not in response", "github_token" not in json.dumps(data))


# ── 2. REST: /api/copilot/models ─────────────────────────────────────────────


def validate_models() -> None:
    print("\n[2] GET /api/copilot/models")
    data = get_json("/api/copilot/models")
    print(f"    response: {json.dumps(data)}")

    check("has 'models' key", "models" in data)
    check("has 'copilot_enabled' key", "copilot_enabled" in data)
    check("has 'sdk_state' key", "sdk_state" in data)
    check("models is list", isinstance(data.get("models"), list))
    check("copilot_enabled is bool", isinstance(data.get("copilot_enabled"), bool))
    check("sdk_state is str", isinstance(data.get("sdk_state"), str))

    # If models are returned, validate their shape
    for m in data.get("models", []):
        required = {"id", "name", "has_vision", "max_tokens", "is_default"}
        check(f"model {m.get('id')} has correct keys", required <= m.keys())


# ── 3. WebSocket: stream a chat message (LangGraph fallback) ──────────────────


async def validate_ws_chat() -> None:
    print("\n[3] WebSocket /ws/chat — send message, check event shapes")
    try:
        import websockets  # type: ignore[import-untyped]
    except ImportError:
        print("    ! websockets not installed — skipping WS tests")
        print("      Install with: .venv/bin/pip install websockets")
        return

    uri = "ws://127.0.0.1:8420/ws/chat"
    received_types: set[str] = set()
    timed_out = False

    try:
        async with websockets.connect(uri, open_timeout=5) as ws:
            await ws.send(json.dumps({"message": "say the word OK and nothing else", "model": ""}))

            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=min(60.0, remaining))
                    event = json.loads(raw)
                    etype = event.get("type", "")
                    received_types.add(etype)
                    if etype in ("stream_end", "error"):
                        break
                except asyncio.TimeoutError:
                    timed_out = True
                    break
    except Exception as exc:
        check("WebSocket connection", False, str(exc))
        return

    if timed_out:
        check("stream completed (no timeout)", False, "timed out waiting for stream_end")
    else:
        check("received stream_start", "stream_start" in received_types)
        check("received stream_token(s)", "stream_token" in received_types)
        check("received stream_end", "stream_end" in received_types)
        check("no unexpected crash", "error" not in received_types or "stream_end" in received_types)


# ── 4. WebSocket: cancel message shape ────────────────────────────────────────


async def validate_ws_cancel() -> None:
    print("\n[4] WebSocket /ws/chat — send {type: cancel} while idle")
    try:
        import websockets  # type: ignore[import-untyped]
    except ImportError:
        return  # already skipped above

    uri = "ws://127.0.0.1:8420/ws/chat"
    try:
        async with websockets.connect(uri, open_timeout=5) as ws:
            # Send cancel with no active task — should be silently ignored (no crash)
            await ws.send(json.dumps({"type": "cancel"}))
            # Give server 0.5 s to respond or not
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                event = json.loads(raw)
                # If something comes back it should be cancelled or nothing bad
                etype = event.get("type", "")
                check("cancel response is 'cancelled' or absent",
                      etype in ("cancelled", "typing"),
                      f"got: {etype}")
            except asyncio.TimeoutError:
                # Silence is fine — idle cancel is a no-op
                check("cancel while idle is silently ignored (no crash)", True)
    except Exception as exc:
        check("WebSocket cancel", False, str(exc))


# ── 5. Security: github_token not in /api/status either ──────────────────────


def validate_token_security() -> None:
    print("\n[5] Security — github_token not leaked in /api/status")
    try:
        data = get_json("/api/status")
        raw = json.dumps(data)
        check("github_token absent from /api/status", "github_token" not in raw)
    except Exception as exc:
        check("/api/status reachable", False, str(exc))


# ── main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    print("=" * 60)
    print("T026 — Copilot SDK Integration Validation")
    print("=" * 60)

    # Wait for server to be ready
    print("\nWaiting for server at", BASE)
    for _ in range(30):
        try:
            urllib.request.urlopen(BASE + "/api/status", timeout=1)
            print("Server ready.")
            break
        except Exception:
            time.sleep(1)
    else:
        print("Server did not start in 30s — aborting.")
        sys.exit(1)

    validate_status()
    validate_models()
    await validate_ws_chat()
    await validate_ws_cancel()
    validate_token_security()

    print("\n" + "=" * 60)
    if failures:
        print(f"FAILED — {len(failures)} check(s) failed:")
        for f in failures:
            print(f"  • {f}")
        sys.exit(1)
    else:
        print(f"PASSED — all checks passed")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

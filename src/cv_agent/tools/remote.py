"""ZeroClaw tools for remote messaging integrations.

These tools let the agent proactively send research updates, digest summaries,
and notifications to Telegram, Discord, WhatsApp, and Signal.
Credentials are read from environment variables at call time so they can be
updated at runtime via the web UI without restarting the server.
"""

from __future__ import annotations

import os
import subprocess

from cv_agent.http_client import httpx
from zeroclaw_tools import tool


# ── Telegram ─────────────────────────────────────────────────────────────────

@tool
def send_telegram_message(message: str) -> str:
    """Send a text message to the configured Telegram chat via the Bot API.

    Useful for notifying about new papers found, digest completion, or any
    research update the user wants pushed to their phone.

    Args:
        message: Markdown-formatted text to send (max ~4096 chars).

    Returns:
        Confirmation or error description.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return "Telegram not configured — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
        if resp.status_code == 200:
            return f"Telegram message sent to chat {chat_id}."
        return f"Telegram error {resp.status_code}: {resp.text[:200]}"
    except Exception as exc:
        return f"Telegram request failed: {exc}"


# ── Discord ───────────────────────────────────────────────────────────────────

@tool
def send_discord_notification(message: str) -> str:
    """Send a notification to the configured Discord webhook.

    Good for team channels — posts the message as a webhook embed.

    Args:
        message: Text to post (max 2000 chars).

    Returns:
        Confirmation or error description.
    """
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        return "Discord not configured — set DISCORD_WEBHOOK_URL."
    try:
        resp = httpx.post(webhook, json={"content": message[:2000]}, timeout=10)
        if resp.status_code in (200, 204):
            return "Discord notification sent."
        return f"Discord error {resp.status_code}: {resp.text[:200]}"
    except Exception as exc:
        return f"Discord request failed: {exc}"


# ── WhatsApp ──────────────────────────────────────────────────────────────────

@tool
def send_whatsapp_message(message: str, recipient: str = "") -> str:
    """Send a WhatsApp message via the Meta Cloud API.

    Requires a Meta Business account, verified phone number, and an approved
    message template for outbound messages to new contacts.

    Args:
        message: Text message to send.
        recipient: E.164 phone number (e.g. +14155552671). Falls back to
                   WHATSAPP_RECIPIENT env var.

    Returns:
        Confirmation or error description.
    """
    token = os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip()
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    to = (recipient or os.environ.get("WHATSAPP_RECIPIENT", "")).strip()
    if not token or not phone_id:
        return "WhatsApp not configured — set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID."
    if not to:
        return "No recipient — set WHATSAPP_RECIPIENT or pass recipient argument."
    try:
        resp = httpx.post(
            f"https://graph.facebook.com/v19.0/{phone_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": message[:4096]},
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return f"WhatsApp message sent to {to}."
        return f"WhatsApp error {resp.status_code}: {resp.text[:200]}"
    except Exception as exc:
        return f"WhatsApp request failed: {exc}"


# ── Signal ────────────────────────────────────────────────────────────────────

@tool
def send_signal_message(message: str, recipient: str = "") -> str:
    """Send a Signal message via signal-cli (must be installed and registered).

    signal-cli is a Java CLI tool — install from https://github.com/AsamK/signal-cli
    and register your phone number before using this tool.

    Args:
        message: Text message to send.
        recipient: E.164 phone number or Signal group ID. Falls back to
                   SIGNAL_RECIPIENT env var.

    Returns:
        Confirmation or error description.
    """
    cli = os.environ.get("SIGNAL_CLI_PATH", "signal-cli").strip()
    sender = os.environ.get("SIGNAL_PHONE_NUMBER", "").strip()
    to = (recipient or os.environ.get("SIGNAL_RECIPIENT", "")).strip()
    if not sender:
        return "Signal not configured — set SIGNAL_PHONE_NUMBER."
    if not to:
        return "No recipient — set SIGNAL_RECIPIENT or pass recipient argument."
    try:
        result = subprocess.run(
            [cli, "-u", sender, "send", "-m", message, to],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return f"Signal message sent to {to}."
        return f"signal-cli error: {(result.stderr or result.stdout).strip()[:300]}"
    except FileNotFoundError:
        return f"signal-cli not found at '{cli}' — install from https://github.com/AsamK/signal-cli"
    except Exception as exc:
        return f"Signal request failed: {exc}"

"""Optional Telegram push for triggered alerts. Deliberately self-contained
(does not import/modify the repo-root signal_agent.py, which already has
its own separate, hardcoded Telegram config for a different workflow) --
this reads its own TELEGRAM_TOKEN/TELEGRAM_CHAT_ID from this app's .env,
and is a no-op if either is unset."""

import requests


def send_telegram(token: str, chat_id: str, message: str) -> None:
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=5,
        )
    except requests.RequestException:
        pass  # best-effort notification, never let this break alert evaluation

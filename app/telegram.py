import html

import httpx

from .config import settings

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_MAX_LEN = 4000


async def send_message(text: str) -> None:
    safe = text[:_MAX_LEN]
    url = _TELEGRAM_API.format(token=settings.telegram_bot_token)
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": safe,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload)
        if response.status_code >= 400:
            payload["text"] = html.escape(safe)
            payload.pop("parse_mode", None)
            response = await client.post(url, json=payload)
        response.raise_for_status()

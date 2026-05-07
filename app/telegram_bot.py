import json
import logging
from datetime import datetime, timezone

import aiosqlite
import httpx

from .config import settings

log = logging.getLogger("telegram_bot")

_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


async def _send(chat_id: str | int, text: str) -> None:
    url = _TELEGRAM_API.format(token=settings.telegram_bot_token, method="sendMessage")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
        except Exception as exc:
            log.warning("telegram send failed: %s", exc)


async def _last_signal() -> dict | None:
    try:
        async with aiosqlite.connect(settings.db_path) as db:
            cursor = await db.execute(
                "SELECT timestamp, ticker, action, score, confidence FROM signals "
                "ORDER BY id DESC LIMIT 1"
            )
            row = await cursor.fetchone()
        if not row:
            return None
        return {
            "timestamp": row[0],
            "ticker": row[1],
            "action": row[2],
            "score": row[3],
            "confidence": row[4],
        }
    except Exception:
        return None


async def _today_count() -> int:
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        async with aiosqlite.connect(settings.db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM signals WHERE timestamp LIKE ?", (f"{today}%",)
            )
            row = await cursor.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


async def _handle_start(chat_id: str | int) -> None:
    text = (
        "👋 <b>أهلاً بك في بوت التنبيهات</b>\n\n"
        "هذا البوت يراقب 10 أسهم أمريكية تلقائيًا ويرسل تنبيهات لما يلقى فرص.\n\n"
        "<b>الأوامر المتاحة:</b>\n"
        "/status — حالة النظام والإحصائيات\n"
        "/test — إرسال تنبيه تجريبي\n"
        "/help — هذه القائمة\n\n"
        "<i>التنبيهات تجي تلقائيًا، ما تحتاج تطلبها.</i>"
    )
    await _send(chat_id, text)


async def _handle_status(chat_id: str | int) -> None:
    last = await _last_signal()
    today = await _today_count()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = ["📊 <b>حالة النظام</b>\n"]
    lines.append(f"الآن: <code>{now}</code>")
    lines.append(f"تنبيهات اليوم: <b>{today}</b>")

    if last:
        lines.append(
            f"\n<b>آخر تنبيه:</b>\n"
            f"السهم: <code>{last['ticker']}</code>\n"
            f"الإجراء: <code>{last['action']}</code>\n"
            f"السكور: <b>{last['score']:.1f}/100</b> ({last['confidence']})\n"
            f"الوقت: <code>{last['timestamp'][:19]}</code>"
        )
    else:
        lines.append("\n<i>لم تصل أي تنبيهات بعد. اصبر، النظام يفحص كل 15 دقيقة.</i>")

    lines.append("\n✅ السيرفر يستجيب")

    await _send(chat_id, "\n".join(lines))


async def _handle_test(chat_id: str | int) -> None:
    text = (
        "🧪 <b>تنبيه تجريبي</b>\n\n"
        "هذي رسالة اختبار لإثبات أن البوت شغّال.\n\n"
        "✅ الاتصال يعمل\n"
        "✅ تيليجرام يستلم\n"
        "✅ النظام نشط\n\n"
        "<i>التنبيهات الحقيقية تجي تلقائيًا حسب حركة الأسواق.</i>"
    )
    await _send(chat_id, text)


async def handle_update(update: dict) -> None:
    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip().lower()

    if not chat_id or not text:
        return

    if text.startswith("/start"):
        await _handle_start(chat_id)
    elif text.startswith("/status"):
        await _handle_status(chat_id)
    elif text.startswith("/test"):
        await _handle_test(chat_id)
    elif text.startswith("/help"):
        await _handle_start(chat_id)
    else:
        await _send(
            chat_id,
            "ما فهمت الأمر. جرّب /status أو /test أو /help",
        )


async def set_webhook(public_url: str) -> bool:
    url = _TELEGRAM_API.format(token=settings.telegram_bot_token, method="setWebhook")
    target = f"{public_url.rstrip('/')}/telegram/webhook"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.post(url, json={"url": target, "allowed_updates": ["message"]})
            return r.status_code == 200 and r.json().get("ok", False)
        except Exception as exc:
            log.warning("set webhook failed: %s", exc)
            return False

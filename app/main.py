import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ai.analyzer import analyze
from .config import settings
from .data.market import fetch_snapshot
from .data.news import fetch_news
from .data.options import fetch_options
from .data.social import fetch_social
from .scanner.runner import run_scan, scanner_loop
from .scoring import compute_score
from .storage import init_db, save_signal
from .telegram import send_message
from .telegram_bot import handle_update as handle_telegram_update

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    task = asyncio.create_task(scanner_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="Trading Signals", lifespan=lifespan)

_static = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_static), name="static")


@app.get("/ar", include_in_schema=False)
async def ar_page():
    return FileResponse(_static / "ar.html", media_type="text/html")


class TradingViewAlert(BaseModel):
    ticker: str
    action: str = Field(description="buy / sell / call / put / etc.")
    price: float | None = None
    strategy: str | None = None
    timeframe: str | None = None
    note: str | None = None


def _format_alert(
    alert: TradingViewAlert,
    score,
    market,
    options,
    news,
    social,
    ai_text: str | None,
) -> str:
    import html as _html

    def esc(value: str) -> str:
        return _html.escape(value)

    lines: list[str] = []
    lines.append(f"<b>{esc(alert.ticker.upper())}</b> — <code>{esc(alert.action.upper())}</code>")
    lines.append(f"الاتجاه: {esc(score.direction)}  |  الثقة: {esc(score.confidence)}")
    lines.append(f"السكور الكلي: <b>{score.total:.1f}/100</b>")
    lines.append("")

    if market:
        rt_badge = " 🟢" if market.is_realtime else " ⏱️"
        lines.append(f"السعر:{rt_badge} <code>{market.price:.2f}</code> ({market.change_pct:+.2f}%)")
        if market.rsi_14 is not None:
            lines.append(f"RSI(14): <code>{market.rsi_14:.1f}</code>")
        if market.volume and market.avg_volume:
            vol_ratio = market.volume / market.avg_volume
            lines.append(f"الفوليوم: {vol_ratio:.2f}× متوسط 30 يوم")
        if market.hv_rank is not None:
            lines.append(
                f"HV Rank: <code>{market.hv_rank:.0f}</code>  |  "
                f"HV20: <code>{market.hv_20:.1%}</code>"
            )
        if market.days_to_earnings is not None:
            if 0 <= market.days_to_earnings <= 14:
                lines.append(
                    f"⚠️ أرباح خلال <b>{market.days_to_earnings}</b> أيام "
                    f"({market.earnings_date})"
                )

    if options:
        lines.append(
            f"P/C Ratio: <code>{options.put_call_ratio:.2f}</code>  |  "
            f"Calls: {options.call_volume:,}  Puts: {options.put_volume:,}"
        )
        lines.append(
            f"IV: Calls <code>{options.avg_call_iv:.2%}</code> / Puts <code>{options.avg_put_iv:.2%}</code>"
        )
        if options.unusual:
            lines.append("⚠️ نشاط أوبشن غير عادي")

    if news:
        lines.append("\n<b>أهم الأخبار:</b>")
        for h in news[:3]:
            lines.append(f"• {esc(h.title[:80])}")

    if social and social.mentions:
        lines.append(
            f"\nسوشيال: {social.mentions} منشور  |  صعود {social.bullish} / هبوط {social.bearish}"
        )

    lines.append(
        f"\n<b>تفصيل السكور:</b> فني <code>{score.technical:.0f}</code> | "
        f"أوبشن <code>{score.options:.0f}</code> | أخبار <code>{score.news:.0f}</code> | "
        f"سوشيال <code>{score.sentiment:.0f}</code>"
    )

    if ai_text:
        lines.append("\n<b>تحليل AI:</b>")
        lines.append(esc(ai_text))

    ticker_upper = alert.ticker.upper()
    lines.append(
        f'\n🔗 <a href="https://www.barchart.com/stocks/quotes/{ticker_upper}/options">Barchart</a>'
        f' | <a href="https://www.tradingview.com/symbols/{ticker_upper}/">TradingView</a>'
        f' | <a href="https://finance.yahoo.com/quote/{ticker_upper}/options">Yahoo</a>'
    )

    if alert.strategy:
        lines.append(f"\n<i>من استراتيجية: {esc(alert.strategy)}</i>")

    return "\n".join(lines)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/scan")
async def trigger_scan() -> dict[str, str]:
    asyncio.create_task(run_scan())
    return {"status": "scan triggered"}


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict[str, str]:
    update = await request.json()
    asyncio.create_task(handle_telegram_update(update))
    return {"ok": "true"}


def _parse_tradingview_text(text: str) -> dict[str, Any] | None:
    import re

    text = text.strip()
    if not text:
        return None

    ticker_match = re.match(r"^([A-Z]{1,6})\b", text)
    if not ticker_match:
        return None

    ticker = ticker_match.group(1)
    action = "buy"
    lowered = text.lower()
    if any(w in lowered for w in ["less than", "crossing down", "below", "sell", "put", "bearish"]):
        action = "sell"
    elif any(w in lowered for w in ["greater than", "crossing up", "above", "buy", "call", "bullish"]):
        action = "buy"

    return {"ticker": ticker, "action": action, "strategy": text[:80]}


@app.post("/webhook")
async def webhook(
    request: Request,
    x_webhook_secret: str | None = Header(default=None),
    secret: str | None = None,
) -> dict[str, Any]:
    body_bytes = await request.body()
    body_text = body_bytes.decode("utf-8", errors="replace")
    body_secret: str | None = None

    try:
        raw = await request.json()
        if isinstance(raw, dict):
            body_secret = raw.pop("secret", None)
        else:
            raw = None
    except Exception:
        raw = None

    if not isinstance(raw, dict):
        parsed = _parse_tradingview_text(body_text)
        if parsed is None:
            raise HTTPException(status_code=400, detail="cannot parse alert")
        raw = parsed

    provided = x_webhook_secret or secret or body_secret
    if provided != settings.webhook_secret:
        raise HTTPException(status_code=401, detail="invalid secret")

    alert = TradingViewAlert(**raw)

    market, options, news, social = await asyncio.gather(
        fetch_snapshot(alert.ticker),
        fetch_options(alert.ticker),
        fetch_news(alert.ticker),
        fetch_social(alert.ticker),
    )

    score = compute_score(alert.action, market, options, news, social)
    ai_text = await analyze(alert.action, market, options, news, social, score)

    message = _format_alert(alert, score, market, options, news, social, ai_text)
    await send_message(message)

    payload = {
        "alert": alert.model_dump(),
        "market": asdict(market) if market else None,
        "options": asdict(options) if options else None,
        "news": [asdict(h) for h in news],
        "social": asdict(social) if social else None,
    }
    await save_signal(
        ticker=alert.ticker.upper(),
        action=alert.action,
        score=score.total,
        direction=score.direction,
        confidence=score.confidence,
        payload=payload,
        ai_analysis=ai_text,
    )

    return {
        "status": "sent",
        "ticker": alert.ticker.upper(),
        "score": score.total,
        "direction": score.direction,
    }

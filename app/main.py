import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .ai.analyzer import analyze
from .config import settings
from .data.market import fetch_snapshot
from .data.news import fetch_news
from .data.options import fetch_options
from .data.social import fetch_social
from .scoring import compute_score
from .storage import init_db, save_signal
from .telegram import send_message


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Trading Signals", lifespan=lifespan)


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
        lines.append(f"السعر: <code>{market.price:.2f}</code> ({market.change_pct:+.2f}%)")
        if market.rsi_14 is not None:
            lines.append(f"RSI(14): <code>{market.rsi_14:.1f}</code>")
        if market.volume and market.avg_volume:
            vol_ratio = market.volume / market.avg_volume
            lines.append(f"الفوليوم: {vol_ratio:.2f}× المتوسط")

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

    if alert.strategy:
        lines.append(f"\n<i>من استراتيجية: {esc(alert.strategy)}</i>")

    return "\n".join(lines)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(
    request: Request,
    x_webhook_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    if x_webhook_secret != settings.webhook_secret:
        raise HTTPException(status_code=401, detail="invalid secret")

    raw = await request.json()
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

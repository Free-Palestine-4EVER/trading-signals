import asyncio
import json
import logging
from dataclasses import asdict
from pathlib import Path

from ..ai.analyzer import analyze
from ..data.market import fetch_snapshot
from ..data.news import fetch_news
from ..data.options import fetch_options
from ..data.social import fetch_social
from ..scoring import compute_score
from ..storage import save_signal
from ..telegram import send_message
from .conditions import ConditionMatch, evaluate
from .dedup import already_fired_today, init_dedup, mark_fired


log = logging.getLogger("scanner")


WATCHLIST_PATH = Path(__file__).resolve().parent.parent.parent / "watchlist.json"


def _load_watchlist() -> dict:
    if not WATCHLIST_PATH.exists():
        return {"scan_interval_minutes": 15, "tickers": [], "conditions": []}
    return json.loads(WATCHLIST_PATH.read_text())


async def _process_match(ticker: str, match: ConditionMatch) -> None:
    if await already_fired_today(ticker, match.name):
        return

    market = await fetch_snapshot(ticker)
    if not market:
        return

    options, news, social = await asyncio.gather(
        fetch_options(ticker),
        fetch_news(ticker),
        fetch_social(ticker),
    )

    score = compute_score(match.action, market, options, news, social)
    ai_text = await analyze(match.action, market, options, news, social, score)

    message = _format_scanner_alert(ticker, match, score, market, options, ai_text)
    await send_message(message)
    await mark_fired(ticker, match.name)

    payload = {
        "scanner": True,
        "condition": match.name,
        "detail": match.detail,
        "market": asdict(market),
        "options": asdict(options) if options else None,
    }
    await save_signal(
        ticker=ticker,
        action=match.action,
        score=score.total,
        direction=score.direction,
        confidence=score.confidence,
        payload=payload,
        ai_analysis=ai_text,
    )


def _format_scanner_alert(ticker, match, score, market, options, ai_text) -> str:
    import html as _html

    def esc(v: str) -> str:
        return _html.escape(v)

    lines = []
    lines.append(f"🔍 <b>فاحص تلقائي</b> — <b>{esc(ticker)}</b>")
    lines.append(f"الشرط: <b>{esc(match.name)}</b>")
    lines.append(f"التفاصيل: {esc(match.detail)}")
    lines.append(f"الإجراء المقترح: <code>{esc(match.action.upper())}</code>")
    lines.append(f"السكور: <b>{score.total:.1f}/100</b>  |  الثقة: {esc(score.confidence)}")
    lines.append("")

    if market:
        lines.append(f"السعر: <code>{market.price:.2f}</code> ({market.change_pct:+.2f}%)")
        if market.rsi_14 is not None:
            lines.append(f"RSI(14): <code>{market.rsi_14:.1f}</code>")
        if market.hv_rank is not None:
            lines.append(f"HV Rank: <code>{market.hv_rank:.0f}</code>")
        if market.days_to_earnings is not None and 0 <= market.days_to_earnings <= 14:
            lines.append(f"⚠️ أرباح خلال {market.days_to_earnings} يوم")

    if options:
        lines.append(
            f"P/C: <code>{options.put_call_ratio:.2f}</code> | "
            f"Calls {options.call_volume:,} / Puts {options.put_volume:,}"
        )
        if options.unusual:
            lines.append("⚠️ نشاط أوبشن غير عادي")

    if ai_text:
        lines.append("\n<b>تحليل AI:</b>")
        lines.append(esc(ai_text))

    lines.append(
        f'\n🔗 <a href="https://www.barchart.com/stocks/quotes/{ticker}/options">Barchart</a>'
        f' | <a href="https://www.tradingview.com/symbols/{ticker}/">TradingView</a>'
    )

    return "\n".join(lines)


async def _scan_ticker(ticker: str, conditions: list[dict]) -> None:
    snapshot = await fetch_snapshot(ticker)
    if not snapshot:
        log.warning("no data for %s", ticker)
        return

    matches = evaluate(snapshot, conditions)
    for m in matches:
        try:
            await _process_match(ticker, m)
        except Exception as exc:
            log.exception("failed to process %s/%s: %s", ticker, m.name, exc)


async def run_scan() -> None:
    config = _load_watchlist()
    tickers = config.get("tickers", [])
    conditions = config.get("conditions", [])
    log.info("scanning %d tickers against %d conditions", len(tickers), len(conditions))
    for ticker in tickers:
        try:
            await _scan_ticker(ticker, conditions)
        except Exception as exc:
            log.exception("scan failed for %s: %s", ticker, exc)
        await asyncio.sleep(5)


async def scanner_loop() -> None:
    await init_dedup()
    while True:
        config = _load_watchlist()
        interval = max(1, int(config.get("scan_interval_minutes", 15)))
        try:
            await run_scan()
        except Exception as exc:
            log.exception("scan failed: %s", exc)
        await asyncio.sleep(interval * 60)

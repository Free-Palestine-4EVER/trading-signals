import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import numpy as np
import yfinance as yf

from ..config import settings


@dataclass
class MarketSnapshot:
    ticker: str
    price: float
    change_pct: float
    volume: int
    avg_volume: int
    rsi_14: float | None
    sma_20: float | None
    sma_50: float | None
    week_high: float
    week_low: float
    hv_20: float | None
    hv_rank: float | None
    hv_percentile: float | None
    earnings_date: str | None
    days_to_earnings: int | None
    is_realtime: bool = False
    data_source: str = "yfinance"


def _rsi(closes: np.ndarray, period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains[-period:].mean()
    avg_loss = losses[-period:].mean()
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def _historical_volatility(closes: np.ndarray, window: int) -> np.ndarray | None:
    if len(closes) < window + 1:
        return None
    log_returns = np.diff(np.log(closes))
    rolling = np.array(
        [log_returns[i - window:i].std() * np.sqrt(252) for i in range(window, len(log_returns) + 1)]
    )
    return rolling


def _earnings_info(ticker_obj: yf.Ticker) -> tuple[str | None, int | None]:
    try:
        cal = ticker_obj.calendar
    except Exception:
        return None, None
    if cal is None:
        return None, None

    earnings_date = None
    if isinstance(cal, dict):
        date_field = cal.get("Earnings Date")
        if isinstance(date_field, list) and date_field:
            earnings_date = date_field[0]
        else:
            earnings_date = date_field

    if earnings_date is None:
        return None, None

    try:
        if hasattr(earnings_date, "date"):
            ed = earnings_date.date()
        else:
            ed = earnings_date
        delta = (ed - datetime.now(timezone.utc).date()).days
        return ed.isoformat(), delta
    except Exception:
        return None, None


def _fetch_sync(ticker: str) -> MarketSnapshot | None:
    t = yf.Ticker(ticker)
    hist = t.history(period="1y", interval="1d")
    if hist.empty:
        return None

    closes = hist["Close"].to_numpy()
    volumes = hist["Volume"].to_numpy()
    last = float(closes[-1])
    prev = float(closes[-2]) if len(closes) > 1 else last
    change_pct = ((last - prev) / prev * 100) if prev else 0.0

    sma_20 = float(closes[-20:].mean()) if len(closes) >= 20 else None
    sma_50 = float(closes[-50:].mean()) if len(closes) >= 50 else None

    hv_series = _historical_volatility(closes, 20)
    hv_20 = float(hv_series[-1]) if hv_series is not None and len(hv_series) else None

    hv_rank = hv_percentile = None
    if hv_series is not None and len(hv_series) >= 50:
        hv_high = float(hv_series.max())
        hv_low = float(hv_series.min())
        if hv_high > hv_low:
            hv_rank = float(((hv_20 - hv_low) / (hv_high - hv_low)) * 100)
        hv_percentile = float((hv_series < hv_20).sum() / len(hv_series) * 100)

    earnings_date, days_to_earnings = _earnings_info(t)

    return MarketSnapshot(
        ticker=ticker.upper(),
        price=last,
        change_pct=change_pct,
        volume=int(volumes[-1]) if len(volumes) else 0,
        avg_volume=int(volumes[-30:].mean()) if len(volumes) >= 30 else int(volumes.mean()),
        rsi_14=_rsi(closes),
        sma_20=sma_20,
        sma_50=sma_50,
        week_high=float(closes[-5:].max()) if len(closes) >= 5 else last,
        week_low=float(closes[-5:].min()) if len(closes) >= 5 else last,
        hv_20=hv_20,
        hv_rank=hv_rank,
        hv_percentile=hv_percentile,
        earnings_date=earnings_date,
        days_to_earnings=days_to_earnings,
    )


async def _fetch_finnhub_quote(ticker: str) -> dict | None:
    if not settings.finnhub_api_key:
        return None
    url = "https://finnhub.io/api/v1/quote"
    params = {"symbol": ticker, "token": settings.finnhub_api_key}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
        if data.get("c", 0) == 0:
            return None
        return data
    except Exception:
        return None


async def fetch_snapshot(ticker: str) -> MarketSnapshot | None:
    snapshot = await asyncio.to_thread(_fetch_sync, ticker)
    if snapshot is None:
        return None

    quote = await _fetch_finnhub_quote(ticker)
    if quote:
        prev_close = quote.get("pc") or snapshot.price
        current = float(quote["c"])
        snapshot.price = current
        snapshot.change_pct = ((current - prev_close) / prev_close * 100) if prev_close else 0.0
        snapshot.is_realtime = True
        snapshot.data_source = "finnhub"

    return snapshot

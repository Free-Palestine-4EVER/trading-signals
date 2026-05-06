import asyncio
from dataclasses import dataclass

import numpy as np
import yfinance as yf


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


def _fetch_sync(ticker: str) -> MarketSnapshot | None:
    t = yf.Ticker(ticker)
    hist = t.history(period="3mo", interval="1d")
    if hist.empty:
        return None

    closes = hist["Close"].to_numpy()
    volumes = hist["Volume"].to_numpy()
    last = float(closes[-1])
    prev = float(closes[-2]) if len(closes) > 1 else last
    change_pct = ((last - prev) / prev * 100) if prev else 0.0

    sma_20 = float(closes[-20:].mean()) if len(closes) >= 20 else None
    sma_50 = float(closes[-50:].mean()) if len(closes) >= 50 else None

    return MarketSnapshot(
        ticker=ticker.upper(),
        price=last,
        change_pct=change_pct,
        volume=int(volumes[-1]) if len(volumes) else 0,
        avg_volume=int(volumes.mean()) if len(volumes) else 0,
        rsi_14=_rsi(closes),
        sma_20=sma_20,
        sma_50=sma_50,
        week_high=float(closes[-5:].max()) if len(closes) >= 5 else last,
        week_low=float(closes[-5:].min()) if len(closes) >= 5 else last,
    )


async def fetch_snapshot(ticker: str) -> MarketSnapshot | None:
    return await asyncio.to_thread(_fetch_sync, ticker)

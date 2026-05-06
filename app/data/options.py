import asyncio
from dataclasses import dataclass

import yfinance as yf


@dataclass
class OptionsSnapshot:
    ticker: str
    expiry: str
    call_volume: int
    put_volume: int
    call_oi: int
    put_oi: int
    avg_call_iv: float
    avg_put_iv: float
    put_call_ratio: float
    unusual: bool


def _fetch_sync(ticker: str) -> OptionsSnapshot | None:
    t = yf.Ticker(ticker)
    expiries = t.options
    if not expiries:
        return None

    expiry = expiries[0]
    chain = t.option_chain(expiry)
    calls = chain.calls
    puts = chain.puts

    if calls.empty and puts.empty:
        return None

    call_vol = int(calls["volume"].fillna(0).sum())
    put_vol = int(puts["volume"].fillna(0).sum())
    call_oi = int(calls["openInterest"].fillna(0).sum())
    put_oi = int(puts["openInterest"].fillna(0).sum())

    avg_call_iv = float(calls["impliedVolatility"].dropna().mean()) if not calls.empty else 0.0
    avg_put_iv = float(puts["impliedVolatility"].dropna().mean()) if not puts.empty else 0.0

    pcr = (put_vol / call_vol) if call_vol else 0.0
    unusual = (call_vol + put_vol) > 0 and (
        call_vol > call_oi * 0.5 or put_vol > put_oi * 0.5
    )

    return OptionsSnapshot(
        ticker=ticker.upper(),
        expiry=expiry,
        call_volume=call_vol,
        put_volume=put_vol,
        call_oi=call_oi,
        put_oi=put_oi,
        avg_call_iv=avg_call_iv,
        avg_put_iv=avg_put_iv,
        put_call_ratio=pcr,
        unusual=unusual,
    )


async def fetch_options(ticker: str) -> OptionsSnapshot | None:
    try:
        return await asyncio.to_thread(_fetch_sync, ticker)
    except Exception:
        return None

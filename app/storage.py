import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from .config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    score REAL,
    direction TEXT,
    confidence TEXT,
    payload_json TEXT,
    ai_analysis TEXT
);

CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker);
CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
"""


async def init_db() -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


async def save_signal(
    ticker: str,
    action: str,
    score: float | None,
    direction: str | None,
    confidence: str | None,
    payload: dict[str, Any],
    ai_analysis: str | None,
) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            INSERT INTO signals
            (timestamp, ticker, action, score, direction, confidence, payload_json, ai_analysis)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                ticker,
                action,
                score,
                direction,
                confidence,
                json.dumps(payload, ensure_ascii=False, default=str),
                ai_analysis,
            ),
        )
        await db.commit()

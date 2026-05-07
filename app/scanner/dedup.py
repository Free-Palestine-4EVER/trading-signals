from datetime import date

import aiosqlite

from ..config import settings


_SCHEMA = """
CREATE TABLE IF NOT EXISTS scanner_fires (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fire_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    condition_name TEXT NOT NULL,
    UNIQUE(fire_date, ticker, condition_name)
);
"""


async def init_dedup() -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


async def already_fired_today(ticker: str, condition_name: str) -> bool:
    today = date.today().isoformat()
    async with aiosqlite.connect(settings.db_path) as db:
        cursor = await db.execute(
            "SELECT 1 FROM scanner_fires WHERE fire_date=? AND ticker=? AND condition_name=?",
            (today, ticker, condition_name),
        )
        row = await cursor.fetchone()
    return row is not None


async def mark_fired(ticker: str, condition_name: str) -> None:
    today = date.today().isoformat()
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            "INSERT OR IGNORE INTO scanner_fires (fire_date, ticker, condition_name) VALUES (?, ?, ?)",
            (today, ticker, condition_name),
        )
        await db.commit()

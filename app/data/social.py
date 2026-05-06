import asyncio
from dataclasses import dataclass

import praw

from ..config import settings


@dataclass
class SocialSnapshot:
    ticker: str
    mentions: int
    bullish: int
    bearish: int
    sample_titles: list[str]


_BULLISH = {"buy", "long", "calls", "moon", "bullish", "pump", "rally", "breakout"}
_BEARISH = {"sell", "short", "puts", "crash", "bearish", "dump", "drop", "breakdown"}


def _fetch_sync(ticker: str, limit: int = 50) -> SocialSnapshot | None:
    if not (settings.reddit_client_id and settings.reddit_client_secret):
        return None

    reddit = praw.Reddit(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        user_agent=settings.reddit_user_agent,
    )

    subs = ["wallstreetbets", "stocks", "options", "investing"]
    bullish = bearish = 0
    titles: list[str] = []

    for sub_name in subs:
        try:
            sub = reddit.subreddit(sub_name)
            for post in sub.search(ticker, limit=limit // len(subs), time_filter="day"):
                title_lower = post.title.lower()
                titles.append(post.title)
                if any(w in title_lower for w in _BULLISH):
                    bullish += 1
                if any(w in title_lower for w in _BEARISH):
                    bearish += 1
        except Exception:
            continue

    return SocialSnapshot(
        ticker=ticker.upper(),
        mentions=len(titles),
        bullish=bullish,
        bearish=bearish,
        sample_titles=titles[:5],
    )


async def fetch_social(ticker: str) -> SocialSnapshot | None:
    return await asyncio.to_thread(_fetch_sync, ticker)

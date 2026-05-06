from dataclasses import dataclass

import httpx

from ..config import settings


@dataclass
class NewsHeadline:
    title: str
    source: str
    url: str
    published_at: str


async def fetch_news(ticker: str, limit: int = 5) -> list[NewsHeadline]:
    if not settings.newsapi_key:
        return []

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": ticker,
        "sortBy": "publishedAt",
        "language": "en",
        "pageSize": limit,
        "apiKey": settings.newsapi_key,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except Exception:
        return []

    return [
        NewsHeadline(
            title=item.get("title", ""),
            source=item.get("source", {}).get("name", ""),
            url=item.get("url", ""),
            published_at=item.get("publishedAt", ""),
        )
        for item in data.get("articles", [])[:limit]
    ]

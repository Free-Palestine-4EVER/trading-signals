from dataclasses import dataclass

from .config import settings
from .data.market import MarketSnapshot
from .data.news import NewsHeadline
from .data.options import OptionsSnapshot
from .data.social import SocialSnapshot


@dataclass
class Score:
    total: float
    technical: float
    options: float
    news: float
    sentiment: float
    direction: str
    confidence: str


def _score_technical(market: MarketSnapshot | None, action: str) -> float:
    if not market:
        return 50.0

    s = 50.0
    bullish = action.lower() in {"buy", "call", "long"}

    if market.rsi_14 is not None:
        if bullish and market.rsi_14 < 30:
            s += 25
        elif not bullish and market.rsi_14 > 70:
            s += 25
        elif bullish and market.rsi_14 > 70:
            s -= 15
        elif not bullish and market.rsi_14 < 30:
            s -= 15

    if market.sma_20 and market.sma_50:
        if bullish and market.sma_20 > market.sma_50:
            s += 10
        elif not bullish and market.sma_20 < market.sma_50:
            s += 10

    if market.volume > market.avg_volume * 1.5:
        s += 10

    return max(0.0, min(100.0, s))


def _score_options(opts: OptionsSnapshot | None, market: MarketSnapshot | None, action: str) -> float:
    if not opts:
        return 50.0

    s = 50.0
    bullish = action.lower() in {"buy", "call", "long"}

    if bullish and opts.put_call_ratio < 0.7:
        s += 20
    elif not bullish and opts.put_call_ratio > 1.3:
        s += 20

    if opts.unusual:
        s += 15

    if bullish and opts.call_volume > opts.put_volume * 2:
        s += 10
    elif not bullish and opts.put_volume > opts.call_volume * 2:
        s += 10

    if market and market.hv_rank is not None:
        if market.hv_rank > 70:
            s += 5
        elif market.hv_rank < 20:
            s -= 5

    if market and market.days_to_earnings is not None:
        if 0 <= market.days_to_earnings <= 7:
            s -= 10

    return max(0.0, min(100.0, s))


def _score_news(headlines: list[NewsHeadline]) -> float:
    if not headlines:
        return 50.0

    positive = {"beats", "surges", "jumps", "rally", "upgrade", "growth", "record", "profit"}
    negative = {"miss", "drops", "falls", "downgrade", "loss", "lawsuit", "crash", "warns"}

    score = 50.0
    for h in headlines:
        title = h.title.lower()
        if any(w in title for w in positive):
            score += 5
        if any(w in title for w in negative):
            score -= 5

    return max(0.0, min(100.0, score))


def _score_sentiment(social: SocialSnapshot | None) -> float:
    if not social or social.mentions == 0:
        return 50.0

    total = social.bullish + social.bearish
    if total == 0:
        return 50.0

    bullish_ratio = social.bullish / total
    return 50.0 + (bullish_ratio - 0.5) * 100


def compute_score(
    action: str,
    market: MarketSnapshot | None,
    options: OptionsSnapshot | None,
    news: list[NewsHeadline],
    social: SocialSnapshot | None,
) -> Score:
    tech = _score_technical(market, action)
    opt = _score_options(options, market, action)
    nws = _score_news(news)
    sent = _score_sentiment(social)

    total = (
        tech * settings.weight_technical
        + opt * settings.weight_options
        + nws * settings.weight_news
        + sent * settings.weight_sentiment
    )

    if total >= 70:
        confidence = "قوية"
    elif total >= 55:
        confidence = "متوسطة"
    elif total >= 40:
        confidence = "ضعيفة"
    else:
        confidence = "ضعيفة جدًا / عكسية"

    bullish = action.lower() in {"buy", "call", "long"}
    direction = "صعود" if bullish else "هبوط"

    return Score(
        total=total,
        technical=tech,
        options=opt,
        news=nws,
        sentiment=sent,
        direction=direction,
        confidence=confidence,
    )

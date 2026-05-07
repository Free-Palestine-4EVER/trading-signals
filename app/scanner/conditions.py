from dataclasses import dataclass

from ..data.market import MarketSnapshot


@dataclass
class ConditionMatch:
    name: str
    action: str
    detail: str


def evaluate(snapshot: MarketSnapshot, conditions: list[dict]) -> list[ConditionMatch]:
    matches: list[ConditionMatch] = []

    for cond in conditions:
        ctype = cond.get("type")
        threshold = cond.get("threshold", 0)
        name = cond.get("name", ctype or "unnamed")
        action = cond.get("action", "info")

        match = _check_condition(snapshot, ctype, threshold)
        if match:
            matches.append(ConditionMatch(name=name, action=action, detail=match))

    return matches


def _check_condition(s: MarketSnapshot, ctype: str | None, threshold: float) -> str | None:
    if ctype == "rsi_below" and s.rsi_14 is not None and s.rsi_14 < threshold:
        return f"RSI={s.rsi_14:.1f} (تحت {threshold})"

    if ctype == "rsi_above" and s.rsi_14 is not None and s.rsi_14 > threshold:
        return f"RSI={s.rsi_14:.1f} (فوق {threshold})"

    if ctype == "volume_ratio_above" and s.volume and s.avg_volume:
        ratio = s.volume / s.avg_volume
        if ratio > threshold:
            return f"الفوليوم {ratio:.1f}× المتوسط"

    if ctype == "price_crosses_above_sma":
        sma = s.sma_50 if threshold == 50 else s.sma_20
        if sma and s.price > sma * 1.001 and s.price < sma * 1.02:
            return f"السعر {s.price:.2f} كسر SMA{int(threshold)} ({sma:.2f}) صعودًا"

    if ctype == "price_crosses_below_sma":
        sma = s.sma_50 if threshold == 50 else s.sma_20
        if sma and s.price < sma * 0.999 and s.price > sma * 0.98:
            return f"السعر {s.price:.2f} كسر SMA{int(threshold)} ({sma:.2f}) هبوطًا"

    if ctype == "hv_rank_above" and s.hv_rank is not None and s.hv_rank > threshold:
        return f"HV Rank={s.hv_rank:.0f} (فوق {threshold})"

    if ctype == "earnings_within_days":
        if s.days_to_earnings is not None and 0 <= s.days_to_earnings <= threshold:
            return f"أرباح خلال {s.days_to_earnings} يوم ({s.earnings_date})"

    return None

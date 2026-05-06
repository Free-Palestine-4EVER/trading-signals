import json
from dataclasses import asdict
from typing import Any

import httpx

from ..config import settings
from ..data.market import MarketSnapshot
from ..data.news import NewsHeadline
from ..data.options import OptionsSnapshot
from ..data.social import SocialSnapshot
from ..scoring import Score


_SYSTEM_PROMPT = """أنت محلل مالي خبير في الأسهم والأوبشن. مهمتك قراءة بيانات السوق المعطاة وإصدار تحليل مختصر وعملي.

قواعد:
- اكتب باللغة العربية
- كن مختصرًا (4-6 أسطر كحد أقصى)
- لا تعطِ نصائح مالية مباشرة، أعطِ ملاحظات تحليلية فقط
- ركّز على ما هو غير عادي أو لافت في البيانات
- اذكر المخاطر بوضوح
- لا تستخدم الإيموجي

الإخراج بهذا الشكل بالضبط:
الاتجاه: [صعود/هبوط/جانبي]
الملاحظات الرئيسية: [3 نقاط مختصرة]
المخاطر: [نقطة أو نقطتين]
"""


def _payload_to_dict(
    action: str,
    market: MarketSnapshot | None,
    options: OptionsSnapshot | None,
    news: list[NewsHeadline],
    social: SocialSnapshot | None,
    score: Score,
) -> dict[str, Any]:
    return {
        "action_signal": action,
        "market": asdict(market) if market else None,
        "options": asdict(options) if options else None,
        "news_headlines": [asdict(h) for h in news[:5]],
        "social": asdict(social) if social else None,
        "score": asdict(score),
    }


def _is_real_anthropic_key(key: str | None) -> bool:
    return bool(key) and key.startswith("sk-ant-api")


async def _analyze_with_gemini(prompt: str) -> str | None:
    import asyncio

    models = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-flash-lite"]
    body = {
        "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 2000,
            "temperature": 0.3,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    last_err = "no models tried"
    for model in models:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={settings.gemini_api_key}"
        )
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.post(url, json=body)
                if r.status_code == 200:
                    data = r.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                if r.status_code in (429, 500, 502, 503, 504):
                    last_err = f"{model}: HTTP {r.status_code}"
                    await asyncio.sleep(2 ** attempt)
                    continue
                last_err = f"{model}: HTTP {r.status_code} - {r.text[:200]}"
                break
            except Exception as exc:
                last_err = f"{model}: {exc}"
                await asyncio.sleep(2 ** attempt)
    return f"(Gemini تعذّر بعد عدة محاولات: {last_err})"


async def _analyze_with_groq(prompt: str) -> str | None:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {settings.groq_api_key}"}
    body = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 400,
        "temperature": 0.3,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        return f"(Groq تعذّر: {exc})"


async def _analyze_with_anthropic(prompt: str) -> str | None:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        return f"(Anthropic تعذّر: {exc})"
    return response.content[0].text if response.content else None


def _rule_based_narrative(
    action: str,
    market: MarketSnapshot | None,
    options: OptionsSnapshot | None,
    score: Score,
) -> str:
    notes: list[str] = []
    risks: list[str] = []

    if market:
        if market.rsi_14 is not None:
            if market.rsi_14 > 70:
                notes.append(f"السهم في منطقة تشبع شراء (RSI={market.rsi_14:.0f})")
                risks.append("احتمال انعكاس قريب بسبب التشبع")
            elif market.rsi_14 < 30:
                notes.append(f"السهم في منطقة تشبع بيع (RSI={market.rsi_14:.0f})")
                risks.append("التشبع البيعي قد يستمر قبل الانعكاس")
            else:
                notes.append(f"RSI متوازن عند {market.rsi_14:.0f}")

        if market.sma_20 and market.sma_50:
            if market.sma_20 > market.sma_50:
                notes.append("اتجاه عام صاعد (SMA20 فوق SMA50)")
            else:
                notes.append("اتجاه عام هابط (SMA20 تحت SMA50)")

        if market.volume > market.avg_volume * 1.5:
            notes.append(f"فوليوم مرتفع ({market.volume / market.avg_volume:.1f}× المتوسط)")

    if options:
        if options.unusual:
            notes.append("نشاط أوبشن غير عادي مرصود")
            risks.append("الحركة غير العادية قد تنعكس بسرعة")
        if options.put_call_ratio < 0.7:
            notes.append(f"P/C ratio منخفض ({options.put_call_ratio:.2f}) — تفاؤل")
        elif options.put_call_ratio > 1.3:
            notes.append(f"P/C ratio مرتفع ({options.put_call_ratio:.2f}) — حذر")

    if not notes:
        notes.append("بيانات محدودة — قرار بناءً على الإشارة الواردة فقط")
    if not risks:
        risks.append("تأكد من إدارة الحجم ووضع stop loss")

    direction = score.direction
    confidence = score.confidence

    parts = [
        f"الاتجاه: {direction}",
        "الملاحظات الرئيسية:",
        *[f"- {n}" for n in notes[:3]],
        "المخاطر:",
        *[f"- {r}" for r in risks[:2]],
        f"الثقة: {confidence} (سكور {score.total:.0f}/100)",
    ]
    return "\n".join(parts)


async def analyze(
    action: str,
    market: MarketSnapshot | None,
    options: OptionsSnapshot | None,
    news: list[NewsHeadline],
    social: SocialSnapshot | None,
    score: Score,
) -> str | None:
    payload = _payload_to_dict(action, market, options, news, social, score)
    prompt = f"حلل البيانات التالية:\n\n{json.dumps(payload, ensure_ascii=False, indent=2)}"

    if _is_real_anthropic_key(settings.anthropic_api_key):
        return await _analyze_with_anthropic(prompt)

    if settings.gemini_api_key:
        return await _analyze_with_gemini(prompt)

    if settings.groq_api_key:
        return await _analyze_with_groq(prompt)

    return _rule_based_narrative(action, market, options, score)

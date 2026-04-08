"""
╔══════════════════════════════════════════════════════════╗
║   MÓDULO DE SENTIMIENTO — ai/sentiment.py                 ║
║   Fear & Greed Index + Binance Funding Rates              ║
║   Detecta extremos emocionales del mercado para modular   ║
║   la agresividad del Agente automáticamente.              ║
╚══════════════════════════════════════════════════════════╝
"""

import logging
import aiohttp
import asyncio
from datetime import datetime

log = logging.getLogger("AgenteBot.Sentiment")

# ── Estado global del sentimiento ──
sentiment_state = {
    "fear_greed_value": 50,       # 0-100
    "fear_greed_label": "Neutral",
    "funding_rate_btc": 0.0,      # % (ej: 0.01 = 0.01%)
    "funding_rate_eth": 0.0,
    "sentiment_signal": "NEUTRAL", # EXTREME_FEAR | FEAR | NEUTRAL | GREED | EXTREME_GREED
    "market_heat": "NORMAL",       # COLD | NORMAL | HOT | OVERHEATED
    "last_update": None,
    "risk_modifier": 1.0,          # Multiplicador para Kelly/Risk (0.3 a 1.5)
}


async def fetch_fear_greed():
    """Consulta el Fear & Greed Index de alternative.me (gratis, sin API key)."""
    try:
        url = "https://api.alternative.me/fng/?limit=1&format=json"
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                if data and "data" in data and len(data["data"]) > 0:
                    entry = data["data"][0]
                    return {
                        "value": int(entry["value"]),
                        "label": entry["value_classification"],
                    }
    except Exception as e:
        log.warning(f"[SENTIMENT] Error Fear&Greed: {e}")
    return None


async def fetch_funding_rates():
    """
    Consulta Funding Rates actuales de BTC y ETH en Binance Futures.
    *NOTA: Aunque este agente opera nativamente en DEXs de Solana via Jupiter, 
    el Funding Rate de Binance actúa como nuestro Macro-Indicador principal. 
    Bitcoin marca el ritmo de liquidez del mercado; si el nivel de apalancamiento es demasiado 
    alto (greed extremo), modulamos el riesgo en todos los clones de Solana para protegernos.*
    """
    rates = {}
    try:
        url = "https://fapi.binance.com/fapi/v1/premiumIndex"
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    return rates
                data = await r.json()
                for item in data:
                    sym = item.get("symbol", "")
                    if sym in ("BTCUSDT", "ETHUSDT"):
                        rates[sym] = float(item.get("lastFundingRate", 0)) * 100  # a porcentaje
    except Exception as e:
        log.warning(f"[SENTIMENT] Error Funding Rates: {e}")
    return rates


def classify_sentiment(fg_value: int) -> str:
    """Clasifica el valor de Fear & Greed en categorías."""
    if fg_value <= 20:
        return "EXTREME_FEAR"
    elif fg_value <= 35:
        return "FEAR"
    elif fg_value <= 65:
        return "NEUTRAL"
    elif fg_value <= 80:
        return "GREED"
    else:
        return "EXTREME_GREED"


def classify_market_heat(funding_btc: float, funding_eth: float) -> str:
    """Clasifica el 'calor' del mercado según funding rates."""
    avg = (abs(funding_btc) + abs(funding_eth)) / 2
    if avg > 0.05:
        return "OVERHEATED"   # Demasiados apalancados, peligro de squeeze
    elif avg > 0.02:
        return "HOT"          # Mercado caliente, precaución
    elif avg < 0.005:
        return "COLD"         # Mercado frío, posible oportunidad
    else:
        return "NORMAL"


def calculate_risk_modifier(signal: str, heat: str, funding_btc: float) -> float:
    """
    Calcula un multiplicador de riesgo basado en sentimiento.
    Este valor modifica directamente el output de Kelly/Risk.
    
    Retorna un float entre 0.3 (ultra-defensivo) y 1.3 (oportunismo).
    """
    modifier = 1.0

    # Fear & Greed modifier
    if signal == "EXTREME_FEAR":
        modifier *= 1.25     # Miedo extremo = oportunidad contraria
    elif signal == "FEAR":
        modifier *= 1.10     # Miedo moderado = ligeramente oportunista
    elif signal == "GREED":
        modifier *= 0.75     # Codicia = precaución
    elif signal == "EXTREME_GREED":
        modifier *= 0.50     # Codicia extrema = modo defensivo total

    # Funding Rate modifier (si BTC funding es muy alto, peligro)
    if funding_btc > 0.05:
        modifier *= 0.60     # Long squeeze inminente
    elif funding_btc > 0.03:
        modifier *= 0.80     # Apalancamiento alto
    elif funding_btc < -0.02:
        modifier *= 1.15     # Short squeeze posible, oportunidad

    # Market heat general
    if heat == "OVERHEATED":
        modifier *= 0.70
    elif heat == "COLD":
        modifier *= 1.10

    # Clamp entre límites seguros
    return max(0.30, min(modifier, 1.30))


async def update_sentiment():
    """Actualiza todo el estado de sentimiento. Llamar cada ~10 min."""
    fg = await fetch_fear_greed()
    fr = await fetch_funding_rates()

    if fg:
        sentiment_state["fear_greed_value"] = fg["value"]
        sentiment_state["fear_greed_label"] = fg["label"]
        sentiment_state["sentiment_signal"] = classify_sentiment(fg["value"])

    btc_fr = fr.get("BTCUSDT", 0.0)
    eth_fr = fr.get("ETHUSDT", 0.0)
    sentiment_state["funding_rate_btc"] = round(btc_fr, 4)
    sentiment_state["funding_rate_eth"] = round(eth_fr, 4)
    sentiment_state["market_heat"] = classify_market_heat(btc_fr, eth_fr)

    sentiment_state["risk_modifier"] = calculate_risk_modifier(
        sentiment_state["sentiment_signal"],
        sentiment_state["market_heat"],
        btc_fr,
    )

    sentiment_state["last_update"] = datetime.now().strftime("%H:%M:%S")

    log.info(
        f"[SENTIMENT] F&G={sentiment_state['fear_greed_value']} "
        f"({sentiment_state['sentiment_signal']}) | "
        f"BTC Funding={btc_fr:+.4f}% | "
        f"Heat={sentiment_state['market_heat']} | "
        f"Risk Mod={sentiment_state['risk_modifier']:.2f}x"
    )

    return sentiment_state


def get_risk_modifier() -> float:
    """Retorna el multiplicador de riesgo actual basado en sentimiento."""
    # Modificador maestro: Si hay Pánico Extremo, operamos con mitad de riesgo (HFT)
    if sentiment_state.get("sentiment_signal") == "EXTREME_FEAR":
        return 0.5
    return sentiment_state.get("risk_modifier", 1.0)


def get_sentiment_summary() -> dict:
    """Retorna el estado completo para el dashboard."""
    return dict(sentiment_state)

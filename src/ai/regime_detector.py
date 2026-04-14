"""
╔══════════════════════════════════════════════════════════╗
║   REGIME DETECTOR — Saber Cuándo NO Operar V3.0          ║
║   Detecta: TRENDING, RANGING, CHOPPY                     ║
║   CHOPPY = NO OPERAR (decisión activa, no pasiva)        ║
╚══════════════════════════════════════════════════════════╝
"""

import logging
import numpy as np
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

from exchange.exchange_adapter import OHLCV

log = logging.getLogger("QuantV3.Regime")


class MarketRegime(Enum):
    TRENDING = "TRENDING"    # ADX > 25, EMAs alineadas → Trend Following
    RANGING = "RANGING"      # ADX < 20, RSI rebotando → Mean Reversion
    CHOPPY = "CHOPPY"        # ADX < 15, sin estructura → NO OPERAR


@dataclass
class RegimeAnalysis:
    """Resultado del análisis de régimen."""
    regime: MarketRegime
    confidence: float         # 0-100%
    adx: float                # Average Directional Index
    atr: float                # Average True Range (volatilidad)
    atr_pct: float            # ATR como % del precio
    trend_direction: str      # "BULLISH" | "BEARISH" | "NEUTRAL"
    ema_alignment: bool       # EMAs 20/50/200 alineadas
    rsi: float                # RSI 14
    volume_trend: str         # "INCREASING" | "DECREASING" | "FLAT"
    recommendation: str       # Descripción legible para el dashboard


class RegimeDetector:
    """
    Analiza la estructura del mercado para determinar el régimen actual.
    
    La capacidad de NO OPERAR cuando el mercado está choppy es lo que
    separa un sistema rentable de uno que pierde dinero lentamente.
    """

    def __init__(self):
        # Umbrales de ADX
        self.adx_trending_threshold = 25    # ADX > 25 → tendencia
        self.adx_ranging_threshold = 20     # ADX < 20 → rango
        self.adx_choppy_threshold = 15      # ADX < 15 → choppy

        # Umbrales de RSI
        self.rsi_oversold = 30
        self.rsi_overbought = 70

    async def detect(self, candles: List[OHLCV], market_symbol: str = "") -> RegimeAnalysis:
        """
        Analiza las velas y determina el régimen del mercado.
        Requiere al menos 55 velas para calcular indicadores.
        """
        if len(candles) < 55:
            return RegimeAnalysis(
                regime=MarketRegime.CHOPPY,
                confidence=0,
                adx=0, atr=0, atr_pct=0,
                trend_direction="NEUTRAL",
                ema_alignment=False,
                rsi=50,
                volume_trend="FLAT",
                recommendation="Datos insuficientes para análisis (necesita 55+ velas)",
            )

        closes = np.array([c.close for c in candles])
        highs = np.array([c.high for c in candles])
        lows = np.array([c.low for c in candles])
        volumes = np.array([c.volume for c in candles])
        current_price = closes[-1]

        # ── Calcular indicadores ──
        adx = self._calculate_adx(highs, lows, closes, period=14)
        atr = self._calculate_atr(highs, lows, closes, period=14)
        atr_pct = (atr / current_price * 100) if current_price > 0 else 0
        rsi = self._calculate_rsi(closes, period=14)
        ema_20 = self._ema(closes, 20)
        ema_50 = self._ema(closes, 50)
        ema_200 = self._ema(closes, min(200, len(closes) - 1)) if len(closes) > 200 else self._ema(closes, len(closes) - 1)

        # ── EMA Alignment ──
        bullish_alignment = ema_20[-1] > ema_50[-1] > ema_200[-1] if len(ema_200) > 0 else False
        bearish_alignment = ema_20[-1] < ema_50[-1] < ema_200[-1] if len(ema_200) > 0 else False
        ema_aligned = bullish_alignment or bearish_alignment

        # ── Trend Direction ──
        if bullish_alignment:
            trend_direction = "BULLISH"
        elif bearish_alignment:
            trend_direction = "BEARISH"
        else:
            trend_direction = "NEUTRAL"

        # ── Volume Trend (últimas 10 vs anteriores 10) ──
        if len(volumes) >= 20 and np.mean(volumes[-20:-10]) > 0:
            vol_ratio = np.mean(volumes[-10:]) / np.mean(volumes[-20:-10])
            if vol_ratio > 1.2:
                volume_trend = "INCREASING"
            elif vol_ratio < 0.8:
                volume_trend = "DECREASING"
            else:
                volume_trend = "FLAT"
        else:
            volume_trend = "FLAT"

        # ── Análisis de mechas (wick analysis) ──
        recent_candles = candles[-10:]
        avg_body = np.mean([abs(c.close - c.open) for c in recent_candles])
        avg_range = np.mean([c.high - c.low for c in recent_candles])
        body_ratio = avg_body / avg_range if avg_range > 0 else 0
        # Body ratio bajo = muchas mechas = mercado choppy
        choppy_wicks = body_ratio < 0.35

        # ══════════════════════════════════════════════════════════
        #  🧠 DETERMINACIÓN DEL RÉGIMEN
        # ══════════════════════════════════════════════════════════

        confidence = 0

        # ── TRENDING ──
        if adx > self.adx_trending_threshold and ema_aligned:
            regime = MarketRegime.TRENDING
            confidence = min(100, 50 + (adx - self.adx_trending_threshold) * 3)
            if volume_trend == "INCREASING":
                confidence = min(100, confidence + 15)
            recommendation = (
                f"📈 TENDENCIA {trend_direction} detectada | ADX: {adx:.1f} | "
                f"EMAs alineadas | Volumen: {volume_trend} | "
                f"→ Usar estrategia TREND FOLLOWING"
            )

        # ── CHOPPY ──
        elif adx < self.adx_choppy_threshold or choppy_wicks:
            regime = MarketRegime.CHOPPY
            confidence = min(100, 50 + (self.adx_choppy_threshold - adx) * 5)
            if choppy_wicks:
                confidence = min(100, confidence + 20)
            recommendation = (
                f"⚠️ MERCADO CHOPPY — NO OPERAR | ADX: {adx:.1f} | "
                f"Body ratio: {body_ratio:.2f} | Volumen: {volume_trend} | "
                f"→ Esperar estructura clara. Esta es una DECISIÓN ACTIVA."
            )

        # ── RANGING ──
        elif adx < self.adx_ranging_threshold:
            regime = MarketRegime.RANGING
            confidence = min(100, 50 + (self.adx_ranging_threshold - adx) * 3)
            # Verificar que RSI está rebotando en los extremos
            rsi_in_range = self.rsi_oversold < rsi < self.rsi_overbought
            if rsi_in_range:
                confidence = min(100, confidence + 10)
            recommendation = (
                f"🔄 MERCADO EN RANGO | ADX: {adx:.1f} | RSI: {rsi:.1f} | "
                f"→ Usar estrategia MEAN REVERSION (solo en extremos)"
            )

        # ── BORDERLINE: ADX entre 20-25 ──
        else:
            if ema_aligned and volume_trend == "INCREASING":
                regime = MarketRegime.TRENDING
                confidence = 40  # Baja confianza
                recommendation = (
                    f"📊 Tendencia débil emergente | ADX: {adx:.1f} | "
                    f"EMAs: {trend_direction} | → Trend following con cautela"
                )
            else:
                regime = MarketRegime.RANGING
                confidence = 45
                recommendation = (
                    f"📊 Mercado indeciso | ADX: {adx:.1f} | "
                    f"→ Mean reversion solo en extremos claros de RSI"
                )

        analysis = RegimeAnalysis(
            regime=regime,
            confidence=confidence,
            adx=round(adx, 2),
            atr=round(atr, 4),
            atr_pct=round(atr_pct, 2),
            trend_direction=trend_direction,
            ema_alignment=ema_aligned,
            rsi=round(rsi, 2),
            volume_trend=volume_trend,
            recommendation=recommendation,
        )

        log.info(
            f"[REGIME] {market_symbol} → {regime.value} ({confidence:.0f}%) | "
            f"ADX: {adx:.1f} | RSI: {rsi:.1f} | Trend: {trend_direction} | "
            f"Vol: {volume_trend}"
        )

        return analysis

    # ══════════════════════════════════════════════════════════
    #  📐 CÁLCULOS TÉCNICOS
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _ema(data: np.ndarray, span: int) -> np.ndarray:
        """Exponential Moving Average."""
        if len(data) < span:
            return data
        alpha = 2 / (span + 1)
        ema = np.zeros_like(data, dtype=float)
        ema[0] = data[0]
        for i in range(1, len(data)):
            ema[i] = data[i] * alpha + ema[i - 1] * (1 - alpha)
        return ema

    @staticmethod
    def _calculate_rsi(closes: np.ndarray, period: int = 14) -> float:
        """Relative Strength Index."""
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _calculate_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
        """Average True Range."""
        if len(closes) < period + 1:
            return 0.0
        tr = np.zeros(len(closes))
        tr[0] = highs[0] - lows[0]
        for i in range(1, len(closes)):
            hl = highs[i] - lows[i]
            hc = abs(highs[i] - closes[i - 1])
            lc = abs(lows[i] - closes[i - 1])
            tr[i] = max(hl, hc, lc)
        # Wilder's smoothing
        atr = np.mean(tr[:period])
        for i in range(period, len(tr)):
            atr = (atr * (period - 1) + tr[i]) / period
        return atr

    @staticmethod
    def _calculate_adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
        """Average Directional Index (Welles Wilder)."""
        n = len(closes)
        if n < period * 2:
            return 10.0  # Default bajo = choppy

        # +DM y -DM
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)
        tr = np.zeros(n)

        for i in range(1, n):
            up_move = highs[i] - highs[i - 1]
            down_move = lows[i - 1] - lows[i]

            plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0
            minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0

            hl = highs[i] - lows[i]
            hc = abs(highs[i] - closes[i - 1])
            lc = abs(lows[i] - closes[i - 1])
            tr[i] = max(hl, hc, lc)

        # Wilder's smoothed
        atr_smooth = np.mean(tr[1:period + 1])
        plus_di_smooth = np.mean(plus_dm[1:period + 1])
        minus_di_smooth = np.mean(minus_dm[1:period + 1])

        dx_values = []
        for i in range(period + 1, n):
            atr_smooth = (atr_smooth * (period - 1) + tr[i]) / period
            plus_di_smooth = (plus_di_smooth * (period - 1) + plus_dm[i]) / period
            minus_di_smooth = (minus_di_smooth * (period - 1) + minus_dm[i]) / period

            if atr_smooth == 0:
                continue

            plus_di = (plus_di_smooth / atr_smooth) * 100
            minus_di = (minus_di_smooth / atr_smooth) * 100
            di_sum = plus_di + minus_di

            if di_sum == 0:
                continue

            dx = abs(plus_di - minus_di) / di_sum * 100
            dx_values.append(dx)

        if not dx_values:
            return 10.0

        # ADX = smoothed average of DX
        if len(dx_values) >= period:
            adx = np.mean(dx_values[:period])
            for i in range(period, len(dx_values)):
                adx = (adx * (period - 1) + dx_values[i]) / period
            return adx
        else:
            return np.mean(dx_values)

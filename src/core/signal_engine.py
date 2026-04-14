"""
╔══════════════════════════════════════════════════════════╗
║   SIGNAL ENGINE — Estrategias de Entrada V3.0            ║
║   Estrategia 1: Trend Following                          ║
║   Estrategia 2: Mean Reversion                           ║
║   Estrategia 3: No Trade (decisión activa)               ║
╚══════════════════════════════════════════════════════════╝
"""

import logging
import numpy as np
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

from exchange.exchange_adapter import OHLCV, PositionDirection
from ai.regime_detector import MarketRegime, RegimeAnalysis

log = logging.getLogger("QuantV3.Signal")


class StrategyType(Enum):
    TREND_FOLLOWING = "TREND_FOLLOWING"
    MEAN_REVERSION = "MEAN_REVERSION"
    NO_TRADE = "NO_TRADE"


@dataclass
class TradeSignal:
    """Señal de entrada generada por el motor de señales."""
    valid: bool
    market_symbol: str
    strategy: StrategyType
    direction: PositionDirection
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    confidence: float          # 0-100%
    reason: str                # Descripción legible
    indicators: dict           # RSI, EMA, etc. para el dashboard

    # Campos para logging
    regime: str = ""
    timeframe: str = "15m"


class SignalEngine:
    """
    Motor de señales de trading.
    Selecciona automáticamente la estrategia según el régimen del mercado.
    
    - TRENDING → Trend Following
    - RANGING  → Mean Reversion
    - CHOPPY   → No Trade
    """

    def __init__(self):
        # ── Trend Following params ──
        self.tf_ema_fast = 20
        self.tf_ema_slow = 50
        self.tf_rsi_long_min = 45     # RSI > 45 para confirmar long
        self.tf_rsi_short_max = 55    # RSI < 55 para confirmar short
        self.tf_min_rr = 1.5          # R:R mínimo para trend following
        self.tf_atr_sl_multiplier = 1.5  # SL = 1.5 × ATR
        self.tf_atr_tp_multiplier = 2.5  # TP = 2.5 × ATR (→ R:R ~1.67)

        # ── Mean Reversion params ──
        self.mr_rsi_oversold = 30
        self.mr_rsi_overbought = 70
        self.mr_bb_period = 20
        self.mr_bb_std = 2.0
        self.mr_min_rr = 1.3         # R:R mínimo para mean reversion
        self.mr_atr_sl_multiplier = 1.2
        self.mr_atr_tp_multiplier = 1.8

    def select_strategy(self, regime: MarketRegime) -> StrategyType:
        """Selecciona la estrategia adecuada según el régimen."""
        if regime == MarketRegime.TRENDING:
            return StrategyType.TREND_FOLLOWING
        elif regime == MarketRegime.RANGING:
            return StrategyType.MEAN_REVERSION
        else:
            return StrategyType.NO_TRADE

    async def scan(
        self,
        market_symbol: str,
        candles: List[OHLCV],
        regime_analysis: RegimeAnalysis,
    ) -> Optional[TradeSignal]:
        """
        Busca una señal de entrada válida para el mercado dado.
        Retorna None si no hay señal o NO_TRADE.
        """
        strategy = self.select_strategy(regime_analysis.regime)

        if strategy == StrategyType.NO_TRADE:
            log.info(f"[SIGNAL] {market_symbol} → NO_TRADE | {regime_analysis.recommendation}")
            return TradeSignal(
                valid=False,
                market_symbol=market_symbol,
                strategy=StrategyType.NO_TRADE,
                direction=PositionDirection.LONG,
                entry_price=0, stop_loss=0, take_profit=0,
                risk_reward=0, confidence=0,
                reason=f"NO TRADE: {regime_analysis.recommendation}",
                indicators={},
                regime=regime_analysis.regime.value,
            )

        if len(candles) < 55:
            return None

        if strategy == StrategyType.TREND_FOLLOWING:
            return self._scan_trend_following(market_symbol, candles, regime_analysis)
        elif strategy == StrategyType.MEAN_REVERSION:
            return self._scan_mean_reversion(market_symbol, candles, regime_analysis)

        return None

    # ══════════════════════════════════════════════════════════
    #  📈 ESTRATEGIA 1: TREND FOLLOWING
    # ══════════════════════════════════════════════════════════

    def _scan_trend_following(
        self,
        market_symbol: str,
        candles: List[OHLCV],
        regime: RegimeAnalysis,
    ) -> Optional[TradeSignal]:
        """
        Busca continuación de tendencia.
        
        Condiciones de entrada (LONG):
          ✅ Tendencia clara (EMAs alineadas bullish)
          ✅ Pullback a EMA 20 (precio tocó o cruzó EMA temporalmente)
          ✅ RSI > 45 (momentum confirmado)
          ✅ Precio rebota desde la EMA (vela de confirmación)
        
        Condiciones de entrada (SHORT):
          ✅ Tendencia clara (EMAs alineadas bearish)
          ✅ Rally a EMA 20 (precio sube hacia resistencia)
          ✅ RSI < 55 (momentum bajista confirmado)
          ✅ Rechazo desde la EMA (vela de confirmación)
        """
        closes = np.array([c.close for c in candles])
        highs = np.array([c.high for c in candles])
        lows = np.array([c.low for c in candles])
        current_price = closes[-1]

        ema_fast = self._ema(closes, self.tf_ema_fast)
        ema_slow = self._ema(closes, self.tf_ema_slow)
        rsi = self._rsi(closes)
        atr = self._atr(highs, lows, closes)

        if atr <= 0:
            return None

        # ── Detectar dirección ──
        bullish = ema_fast[-1] > ema_slow[-1]
        bearish = ema_fast[-1] < ema_slow[-1]

        indicators = {
            "ema_fast": round(ema_fast[-1], 2),
            "ema_slow": round(ema_slow[-1], 2),
            "rsi": round(rsi, 1),
            "atr": round(atr, 4),
            "adx": regime.adx,
        }

        # ── LONG SETUP ──
        if bullish and regime.trend_direction == "BULLISH":
            # ¿Pullback a EMA 20?
            # El precio debe estar cerca de la EMA rápida (dentro de 1 ATR)
            distance_to_ema = current_price - ema_fast[-1]
            near_ema = -atr * 0.5 <= distance_to_ema <= atr * 1.0

            # ¿RSI confirma momentum?
            rsi_ok = rsi > self.tf_rsi_long_min

            # ¿Vela de rebote? (cierre > apertura y mínimo cerca de EMA)
            last_candle = candles[-1]
            prev_candle = candles[-2]
            bounce = last_candle.close > last_candle.open and last_candle.low <= ema_fast[-1] * 1.005

            if near_ema and rsi_ok and (bounce or distance_to_ema < atr * 0.3):
                sl = current_price - (atr * self.tf_atr_sl_multiplier)
                tp = current_price + (atr * self.tf_atr_tp_multiplier)
                rr = (tp - current_price) / (current_price - sl) if (current_price - sl) > 0 else 0

                if rr >= self.tf_min_rr:
                    return TradeSignal(
                        valid=True,
                        market_symbol=market_symbol,
                        strategy=StrategyType.TREND_FOLLOWING,
                        direction=PositionDirection.LONG,
                        entry_price=current_price,
                        stop_loss=round(sl, 4),
                        take_profit=round(tp, 4),
                        risk_reward=round(rr, 2),
                        confidence=min(95, regime.confidence),
                        reason=(
                            f"TREND LONG: Pullback a EMA{self.tf_ema_fast} en tendencia alcista | "
                            f"RSI: {rsi:.0f} | ADX: {regime.adx:.0f} | R:R: {rr:.2f}"
                        ),
                        indicators=indicators,
                        regime=regime.regime.value,
                    )

        # ── SHORT SETUP ──
        elif bearish and regime.trend_direction == "BEARISH":
            distance_to_ema = ema_fast[-1] - current_price
            near_ema = -atr * 0.5 <= distance_to_ema <= atr * 1.0

            rsi_ok = rsi < self.tf_rsi_short_max

            last_candle = candles[-1]
            rejection = last_candle.close < last_candle.open and last_candle.high >= ema_fast[-1] * 0.995

            if near_ema and rsi_ok and (rejection or distance_to_ema < atr * 0.3):
                sl = current_price + (atr * self.tf_atr_sl_multiplier)
                tp = current_price - (atr * self.tf_atr_tp_multiplier)
                rr = (current_price - tp) / (sl - current_price) if (sl - current_price) > 0 else 0

                if rr >= self.tf_min_rr:
                    return TradeSignal(
                        valid=True,
                        market_symbol=market_symbol,
                        strategy=StrategyType.TREND_FOLLOWING,
                        direction=PositionDirection.SHORT,
                        entry_price=current_price,
                        stop_loss=round(sl, 4),
                        take_profit=round(tp, 4),
                        risk_reward=round(rr, 2),
                        confidence=min(95, regime.confidence),
                        reason=(
                            f"TREND SHORT: Rally a EMA{self.tf_ema_fast} en tendencia bajista | "
                            f"RSI: {rsi:.0f} | ADX: {regime.adx:.0f} | R:R: {rr:.2f}"
                        ),
                        indicators=indicators,
                        regime=regime.regime.value,
                    )

        return None

    # ══════════════════════════════════════════════════════════
    #  🧲 ESTRATEGIA 2: MEAN REVERSION
    # ══════════════════════════════════════════════════════════

    def _scan_mean_reversion(
        self,
        market_symbol: str,
        candles: List[OHLCV],
        regime: RegimeAnalysis,
    ) -> Optional[TradeSignal]:
        """
        Busca retrocesos al promedio en mercados en rango.
        
        Condiciones de entrada (LONG):
          ✅ RSI < 30 (sobrevendido)
          ✅ Precio toca Bollinger Band inferior
          ✅ Vela de rechazo (mecha larga inferior)
          ❌ NO usar si ADX > 25 (tendencia fuerte)
        
        Condiciones de entrada (SHORT):
          ✅ RSI > 70 (sobrecomprado)
          ✅ Precio toca Bollinger Band superior
          ✅ Vela de rechazo (mecha larga superior)
          ❌ NO usar si ADX > 25 (tendencia fuerte)
        """
        # Safety check: NUNCA mean reversion en tendencia fuerte
        if regime.adx > 25:
            return None

        closes = np.array([c.close for c in candles])
        highs = np.array([c.high for c in candles])
        lows = np.array([c.low for c in candles])
        current_price = closes[-1]

        rsi = self._rsi(closes)
        atr = self._atr(highs, lows, closes)
        bb_upper, bb_middle, bb_lower = self._bollinger_bands(closes, self.mr_bb_period, self.mr_bb_std)

        if atr <= 0 or bb_upper == 0:
            return None

        indicators = {
            "rsi": round(rsi, 1),
            "atr": round(atr, 4),
            "bb_upper": round(bb_upper, 4),
            "bb_middle": round(bb_middle, 4),
            "bb_lower": round(bb_lower, 4),
            "adx": regime.adx,
        }

        last_candle = candles[-1]

        # ── LONG: Sobrevendido ──
        if rsi < self.mr_rsi_oversold and current_price <= bb_lower * 1.005:
            # Verificar vela de rechazo (mecha inferior larga)
            body = abs(last_candle.close - last_candle.open)
            lower_wick = min(last_candle.open, last_candle.close) - last_candle.low
            has_rejection = lower_wick > body * 1.5

            if has_rejection or rsi < 25:  # RSI muy extremo = señal fuerte
                sl = current_price - (atr * self.mr_atr_sl_multiplier)
                tp = bb_middle  # Target: banda media (EMA 20)
                rr = (tp - current_price) / (current_price - sl) if (current_price - sl) > 0 else 0

                if rr >= self.mr_min_rr:
                    return TradeSignal(
                        valid=True,
                        market_symbol=market_symbol,
                        strategy=StrategyType.MEAN_REVERSION,
                        direction=PositionDirection.LONG,
                        entry_price=current_price,
                        stop_loss=round(sl, 4),
                        take_profit=round(tp, 4),
                        risk_reward=round(rr, 2),
                        confidence=min(80, 40 + (self.mr_rsi_oversold - rsi) * 3),
                        reason=(
                            f"MR LONG: RSI {rsi:.0f} sobrevendido + toque BB inferior | "
                            f"Target: BB media ${bb_middle:.2f} | R:R: {rr:.2f}"
                        ),
                        indicators=indicators,
                        regime=regime.regime.value,
                    )

        # ── SHORT: Sobrecomprado ──
        elif rsi > self.mr_rsi_overbought and current_price >= bb_upper * 0.995:
            body = abs(last_candle.close - last_candle.open)
            upper_wick = last_candle.high - max(last_candle.open, last_candle.close)
            has_rejection = upper_wick > body * 1.5

            if has_rejection or rsi > 75:
                sl = current_price + (atr * self.mr_atr_sl_multiplier)
                tp = bb_middle
                rr = (current_price - tp) / (sl - current_price) if (sl - current_price) > 0 else 0

                if rr >= self.mr_min_rr:
                    return TradeSignal(
                        valid=True,
                        market_symbol=market_symbol,
                        strategy=StrategyType.MEAN_REVERSION,
                        direction=PositionDirection.SHORT,
                        entry_price=current_price,
                        stop_loss=round(sl, 4),
                        take_profit=round(tp, 4),
                        risk_reward=round(rr, 2),
                        confidence=min(80, 40 + (rsi - self.mr_rsi_overbought) * 3),
                        reason=(
                            f"MR SHORT: RSI {rsi:.0f} sobrecomprado + toque BB superior | "
                            f"Target: BB media ${bb_middle:.2f} | R:R: {rr:.2f}"
                        ),
                        indicators=indicators,
                        regime=regime.regime.value,
                    )

        return None

    # ══════════════════════════════════════════════════════════
    #  📐 CÁLCULOS TÉCNICOS
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _ema(data: np.ndarray, span: int) -> np.ndarray:
        alpha = 2 / (span + 1)
        ema = np.zeros_like(data, dtype=float)
        ema[0] = data[0]
        for i in range(1, len(data)):
            ema[i] = data[i] * alpha + ema[i - 1] * (1 - alpha)
        return ema

    @staticmethod
    def _rsi(closes: np.ndarray, period: int = 14) -> float:
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
    def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 0.0
        tr = np.zeros(len(closes))
        tr[0] = highs[0] - lows[0]
        for i in range(1, len(closes)):
            tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        atr = np.mean(tr[:period])
        for i in range(period, len(tr)):
            atr = (atr * (period - 1) + tr[i]) / period
        return atr

    @staticmethod
    def _bollinger_bands(closes: np.ndarray, period: int = 20, std_dev: float = 2.0):
        if len(closes) < period:
            return 0, 0, 0
        window = closes[-period:]
        sma = np.mean(window)
        std = np.std(window)
        return sma + std_dev * std, sma, sma - std_dev * std

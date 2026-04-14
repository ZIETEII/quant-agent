"""
╔══════════════════════════════════════════════════════════╗
║   RISK ENGINE — El Corazón de la Disciplina V3.0         ║
║   Controla: Daily Caps, Per-Trade Risk, Kill Switches,   ║
║   Cooldowns, y Anti-Patterns                             ║
╚══════════════════════════════════════════════════════════╝

REGLAS DE ORO:
  ❌ Sin martingala
  ❌ Sin "recuperar pérdidas"
  ❌ Sin trades sin stop
  ❌ Máximo 1-2 posiciones simultáneas
  ❌ NUNCA usar 100% del capital
"""

import os
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, Dict, Any

log = logging.getLogger("QuantV3.Risk")


@dataclass
class DailySession:
    """Estado de la sesión diaria de trading."""
    date: str                        # YYYY-MM-DD
    realized_pnl: float = 0.0       # PnL realizado del día
    trade_count: int = 0             # Trades ejecutados hoy
    win_count: int = 0               # Wins del día
    loss_count: int = 0              # Losses del día
    consecutive_losses: int = 0      # Pérdidas seguidas actuales
    max_consecutive_losses: int = 0  # Máximo streak del día
    largest_win: float = 0.0         # Mayor ganancia
    largest_loss: float = 0.0        # Mayor pérdida
    started_at: str = ""             # Hora de inicio de operaciones


@dataclass
class RiskDecision:
    """Resultado de una evaluación de riesgo."""
    approved: bool
    reason: str
    risk_amount: float = 0.0         # USD que se arriesga
    position_size: float = 0.0       # Tamaño de posición en unidades
    leverage: float = 1.0
    stop_loss: float = 0.0           # Precio de stop loss
    take_profit: float = 0.0         # Precio de take profit
    rr_ratio: float = 0.0            # Risk/Reward ratio


class RiskEngine:
    """
    Motor de gestión de riesgo. Todas las decisiones de riesgo pasan por aquí.
    
    Principio fundamental: la preservación de capital por encima de todo.
    """

    def __init__(self):
        # ── Configuración de capital ──
        self.trading_capital = float(os.getenv("TRADING_CAPITAL", "5000"))
        self.reserve_capital = float(os.getenv("RESERVE_CAPITAL", "2000"))

        # ── Límites diarios ──
        self.daily_profit_cap = float(os.getenv("DAILY_PROFIT_CAP", "600"))
        self.daily_loss_cap = float(os.getenv("DAILY_LOSS_CAP", "300"))
        self.max_daily_trades = int(os.getenv("MAX_DAILY_TRADES", "12"))
        self.max_consecutive_losses = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "3"))

        # ── Riesgo por trade ──
        self.risk_per_trade_pct = float(os.getenv("RISK_PER_TRADE_PCT", "0.50")) / 100  # 0.50% = 0.005
        self.min_rr_ratio = float(os.getenv("MIN_RR_RATIO", "1.3"))
        self.max_open_positions = int(os.getenv("MAX_OPEN_POSITIONS", "2"))

        # ── Cooldowns (segundos) ──
        self.cooldown_after_win = int(os.getenv("COOLDOWN_AFTER_WIN", "300"))      # 5 min
        self.cooldown_after_loss = int(os.getenv("COOLDOWN_AFTER_LOSS", "900"))     # 15 min
        self.cooldown_after_streak = int(os.getenv("COOLDOWN_AFTER_STREAK", "1800"))  # 30 min

        # ── Umbrales de protección ──
        self.max_funding_rate = 0.05     # No entrar si funding > 0.05% contra la dirección
        self.max_spread_pct = 0.10       # No entrar si spread > 0.10%
        self.max_slippage_pct = 0.30     # Kill switch si slippage > 0.30%

        # ── Estado ──
        self._session = DailySession(date=date.today().isoformat())
        self._cooldown_until: float = 0  # Timestamp
        self._last_trade_result: Optional[str] = None  # "win" | "loss"

        log.info(
            f"[RISK ENGINE] Inicializado | Capital: ${self.trading_capital:,.0f} | "
            f"Profit Cap: +${self.daily_profit_cap:,.0f} | Loss Cap: -${self.daily_loss_cap:,.0f} | "
            f"Risk/Trade: {self.risk_per_trade_pct*100:.2f}% (${self.trading_capital * self.risk_per_trade_pct:.0f})"
        )

    # ══════════════════════════════════════════════════════════
    #  🔍 VALIDACIÓN DE TRADE
    # ══════════════════════════════════════════════════════════

    def validate_entry(
        self,
        entry_price: float,
        stop_loss_price: float,
        take_profit_price: float,
        direction: str,  # "LONG" | "SHORT"
        current_positions: int,
        funding_rate: float = 0.0,
        spread_pct: float = 0.0,
    ) -> RiskDecision:
        """
        Evalúa si un trade potencial cumple todas las reglas de riesgo.
        Este es el portero final antes de cualquier ejecución.
        """

        # ── 1. Verificar sesión diaria (reset si cambió el día) ──
        self._check_daily_reset()

        # ── 2. ¿Profit Cap alcanzado? ──
        if self._session.realized_pnl >= self.daily_profit_cap:
            return RiskDecision(
                approved=False,
                reason=f"PROFIT_CAP: Meta diaria alcanzada (+${self._session.realized_pnl:,.2f} / +${self.daily_profit_cap:,.0f})",
            )

        # ── 3. ¿Loss Cap alcanzado? ──
        if self._session.realized_pnl <= -self.daily_loss_cap:
            return RiskDecision(
                approved=False,
                reason=f"LOSS_CAP: Límite de pérdida diaria alcanzado (${self._session.realized_pnl:,.2f} / -${self.daily_loss_cap:,.0f})",
            )

        # ── 4. ¿Máximo de trades diarios? ──
        if self._session.trade_count >= self.max_daily_trades:
            return RiskDecision(
                approved=False,
                reason=f"MAX_TRADES: Límite diario alcanzado ({self._session.trade_count}/{self.max_daily_trades})",
            )

        # ── 5. ¿En cooldown? ──
        if self.is_in_cooldown():
            remaining = int(self._cooldown_until - time.time())
            return RiskDecision(
                approved=False,
                reason=f"COOLDOWN: Esperando {remaining}s antes del siguiente trade",
            )

        # ── 6. ¿Pérdidas consecutivas? ──
        if self._session.consecutive_losses >= self.max_consecutive_losses:
            return RiskDecision(
                approved=False,
                reason=f"STREAK_STOP: {self._session.consecutive_losses} pérdidas consecutivas (max: {self.max_consecutive_losses})",
            )

        # ── 7. ¿Máximo de posiciones abiertas? ──
        if current_positions >= self.max_open_positions:
            return RiskDecision(
                approved=False,
                reason=f"MAX_POSITIONS: Ya hay {current_positions}/{self.max_open_positions} posiciones abiertas",
            )

        # ── 8. ¿Spread aceptable? ──
        if spread_pct > self.max_spread_pct:
            return RiskDecision(
                approved=False,
                reason=f"HIGH_SPREAD: Spread {spread_pct:.3f}% > máximo {self.max_spread_pct:.3f}%",
            )

        # ── 9. ¿Funding rate contra la posición? ──
        if direction == "LONG" and funding_rate > self.max_funding_rate:
            return RiskDecision(
                approved=False,
                reason=f"FUNDING_ADVERSE: Funding rate {funding_rate:.4f}% demasiado alto para LONG",
            )
        elif direction == "SHORT" and funding_rate < -self.max_funding_rate:
            return RiskDecision(
                approved=False,
                reason=f"FUNDING_ADVERSE: Funding rate {funding_rate:.4f}% demasiado negativo para SHORT",
            )

        # ── 10. Calcular Risk/Reward ──
        if direction == "LONG":
            risk_distance = entry_price - stop_loss_price
            reward_distance = take_profit_price - entry_price
        else:  # SHORT
            risk_distance = stop_loss_price - entry_price
            reward_distance = entry_price - take_profit_price

        if risk_distance <= 0:
            return RiskDecision(
                approved=False,
                reason=f"INVALID_SL: Stop loss mal colocado (distancia: {risk_distance:.4f})",
            )

        rr_ratio = reward_distance / risk_distance if risk_distance > 0 else 0

        if rr_ratio < self.min_rr_ratio:
            return RiskDecision(
                approved=False,
                reason=f"LOW_RR: R:R {rr_ratio:.2f} < mínimo {self.min_rr_ratio:.1f}",
            )

        # ── 11. Calcular tamaño de posición ──
        risk_amount = self.trading_capital * self.risk_per_trade_pct
        risk_pct_of_entry = risk_distance / entry_price
        position_notional = risk_amount / risk_pct_of_entry if risk_pct_of_entry > 0 else 0
        position_size = position_notional / entry_price if entry_price > 0 else 0

        # Leverage implícito
        leverage = position_notional / self.trading_capital if self.trading_capital > 0 else 1.0
        leverage = min(leverage, 3.0)  # Hard cap 3x

        # ── 12. Verificar que fees < beneficio esperado ──
        estimated_fees = position_notional * 0.002  # ~0.1% entry + 0.1% exit
        expected_profit = risk_amount * rr_ratio
        if estimated_fees > expected_profit * 0.3:  # Fees > 30% del beneficio esperado
            return RiskDecision(
                approved=False,
                reason=f"FEE_PROHIBITIVE: Fees estimados (${estimated_fees:.2f}) > 30% del beneficio esperado (${expected_profit:.2f})",
            )

        # ── ✅ APROBADO ──
        return RiskDecision(
            approved=True,
            reason=f"APPROVED: R:R {rr_ratio:.2f} | Risk ${risk_amount:.2f} | Size {position_size:.4f}",
            risk_amount=risk_amount,
            position_size=position_size,
            leverage=leverage,
            stop_loss=stop_loss_price,
            take_profit=take_profit_price,
            rr_ratio=rr_ratio,
        )

    # ══════════════════════════════════════════════════════════
    #  📊 REGISTRO DE RESULTADOS
    # ══════════════════════════════════════════════════════════

    def record_trade_result(self, pnl: float, is_win: bool) -> dict:
        """
        Registra el resultado de un trade cerrado.
        Retorna el nuevo estado de la sesión.
        """
        self._check_daily_reset()

        self._session.realized_pnl += pnl
        self._session.trade_count += 1

        if is_win:
            self._session.win_count += 1
            self._session.consecutive_losses = 0
            self._last_trade_result = "win"
            if pnl > self._session.largest_win:
                self._session.largest_win = pnl
        else:
            self._session.loss_count += 1
            self._session.consecutive_losses += 1
            self._last_trade_result = "loss"
            if pnl < self._session.largest_loss:
                self._session.largest_loss = pnl

        if self._session.consecutive_losses > self._session.max_consecutive_losses:
            self._session.max_consecutive_losses = self._session.consecutive_losses

        # ── Activar cooldown ──
        self._activate_cooldown()

        # ── Log estado ──
        log.info(
            f"[RISK] Trade #{self._session.trade_count} | "
            f"{'WIN' if is_win else 'LOSS'} ${pnl:+.2f} | "
            f"Day PnL: ${self._session.realized_pnl:+.2f} | "
            f"WR: {self._session.win_count}/{self._session.trade_count} | "
            f"Streak: {self._session.consecutive_losses} losses"
        )

        return self.get_session_state()

    # ══════════════════════════════════════════════════════════
    #  ⏱️ COOLDOWNS
    # ══════════════════════════════════════════════════════════

    def _activate_cooldown(self):
        """Activa el cooldown apropiado según el resultado."""
        if self._session.consecutive_losses >= 2:
            # Múltiples pérdidas seguidas → pausa larga
            duration = self.cooldown_after_streak
            log.info(f"[RISK] Cooldown largo activado: {duration}s ({self._session.consecutive_losses} losses seguidas)")
        elif self._last_trade_result == "loss":
            duration = self.cooldown_after_loss
            log.info(f"[RISK] Cooldown post-loss: {duration}s")
        else:
            duration = self.cooldown_after_win
            log.info(f"[RISK] Cooldown post-win: {duration}s")

        self._cooldown_until = time.time() + duration

    def is_in_cooldown(self) -> bool:
        """¿El bot está en período de enfriamiento?"""
        return time.time() < self._cooldown_until

    def get_cooldown_remaining(self) -> int:
        """Segundos restantes de cooldown."""
        return max(0, int(self._cooldown_until - time.time()))

    # ══════════════════════════════════════════════════════════
    #  🔄 GESTIÓN DE SESIÓN
    # ══════════════════════════════════════════════════════════

    def _check_daily_reset(self):
        """Resetea la sesión si cambió el día."""
        today = date.today().isoformat()
        if self._session.date != today:
            log.info(f"[RISK] 📅 Nuevo día detectado. Reseteando sesión diaria.")
            old_session = self._session
            self._session = DailySession(
                date=today,
                started_at=datetime.now().strftime("%H:%M:%S"),
            )
            self._cooldown_until = 0
            self._last_trade_result = None
            return old_session
        return None

    def get_session_state(self) -> dict:
        """Retorna el estado completo de la sesión para dashboard/logs."""
        self._check_daily_reset()
        return {
            "date": self._session.date,
            "realized_pnl": round(self._session.realized_pnl, 2),
            "trade_count": self._session.trade_count,
            "win_count": self._session.win_count,
            "loss_count": self._session.loss_count,
            "win_rate": round(self._session.win_count / self._session.trade_count * 100, 1) if self._session.trade_count > 0 else 0,
            "consecutive_losses": self._session.consecutive_losses,
            "max_consecutive_losses": self._session.max_consecutive_losses,
            "largest_win": round(self._session.largest_win, 2),
            "largest_loss": round(self._session.largest_loss, 2),
            # Caps
            "profit_cap": self.daily_profit_cap,
            "loss_cap": self.daily_loss_cap,
            "profit_cap_pct": round(self._session.realized_pnl / self.daily_profit_cap * 100, 1) if self.daily_profit_cap > 0 else 0,
            "loss_cap_pct": round(abs(min(0, self._session.realized_pnl)) / self.daily_loss_cap * 100, 1) if self.daily_loss_cap > 0 else 0,
            "profit_cap_reached": self._session.realized_pnl >= self.daily_profit_cap,
            "loss_cap_reached": self._session.realized_pnl <= -self.daily_loss_cap,
            # Cooldown
            "in_cooldown": self.is_in_cooldown(),
            "cooldown_remaining": self.get_cooldown_remaining(),
            # Config
            "risk_per_trade_usd": round(self.trading_capital * self.risk_per_trade_pct, 2),
            "risk_per_trade_pct": round(self.risk_per_trade_pct * 100, 2),
            "max_daily_trades": self.max_daily_trades,
            "trades_remaining": max(0, self.max_daily_trades - self._session.trade_count),
            "max_open_positions": self.max_open_positions,
        }

    # ══════════════════════════════════════════════════════════
    #  🚨 KILL SWITCHES
    # ══════════════════════════════════════════════════════════

    def should_emergency_stop(self, slippage_pct: float = 0, api_healthy: bool = True) -> Optional[str]:
        """
        Verifica condiciones de parada de emergencia.
        Retorna None si todo ok, o un string con la razón del kill.
        """
        if not api_healthy:
            return "KILL: API/conexión al exchange no responde"

        if slippage_pct > self.max_slippage_pct:
            return f"KILL: Slippage detectado {slippage_pct:.2f}% > máximo {self.max_slippage_pct:.2f}%"

        if self._session.realized_pnl <= -self.daily_loss_cap:
            return f"KILL: Loss cap diario alcanzado (${self._session.realized_pnl:+.2f})"

        if self._session.consecutive_losses >= self.max_consecutive_losses + 1:
            return f"KILL: {self._session.consecutive_losses} pérdidas consecutivas"

        return None

"""
╔══════════════════════════════════════════════════════════╗
║   POSITION SIZER — Cálculo de Tamaño de Posición V3.0    ║
║   Siempre basado en: riesgo por trade + distancia al stop║
║   NUNCA basado en "cuánto quiero ganar hoy"              ║
╚══════════════════════════════════════════════════════════╝
"""

import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("QuantV3.Sizer")


@dataclass
class SizeResult:
    """Resultado del cálculo de tamaño de posición."""
    position_size: float          # Unidades base (ej: 1.5 SOL)
    position_notional: float      # Valor en USD de la posición
    margin_required: float        # Colateral necesario
    risk_amount: float            # USD en riesgo si SL se ejecuta
    leverage_used: float          # Apalancamiento efectivo
    risk_reward_ratio: float      # R:R del setup
    stop_loss_distance_pct: float # Distancia al SL en %
    valid: bool                   # Si el cálculo es válido
    reason: str = ""              # Razón de rechazo si no es válido


def calculate_position_size(
    capital: float,
    risk_per_trade_pct: float,
    entry_price: float,
    stop_loss_price: float,
    take_profit_price: float,
    direction: str,              # "LONG" | "SHORT"
    max_leverage: float = 3.0,
    min_order_size: float = 0.01,
) -> SizeResult:
    """
    Calcula el tamaño óptimo de posición basado en el riesgo.
    
    Fórmula:
        risk_amount = capital × risk_per_trade_pct
        distance_to_stop = |entry - stop| / entry
        position_notional = risk_amount / distance_to_stop
        position_size = position_notional / entry_price
    
    Ejemplo con $5,000 capital, 0.50% riesgo, SOL @ $150, SL @ $147:
        risk_amount = $5,000 × 0.005 = $25
        distance = ($150 - $147) / $150 = 2.0%
        position_notional = $25 / 0.02 = $1,250
        position_size = $1,250 / $150 = 8.33 SOL
        leverage = $1,250 / $5,000 = 0.25x
    """
    
    # Validaciones básicas
    if capital <= 0 or entry_price <= 0:
        return SizeResult(
            position_size=0, position_notional=0, margin_required=0,
            risk_amount=0, leverage_used=0, risk_reward_ratio=0,
            stop_loss_distance_pct=0, valid=False,
            reason="Capital o precio de entrada inválido",
        )

    if stop_loss_price <= 0:
        return SizeResult(
            position_size=0, position_notional=0, margin_required=0,
            risk_amount=0, leverage_used=0, risk_reward_ratio=0,
            stop_loss_distance_pct=0, valid=False,
            reason="Stop loss no definido (NUNCA operar sin stop)",
        )

    # ── Calcular distancias ──
    if direction == "LONG":
        risk_distance = entry_price - stop_loss_price
        reward_distance = take_profit_price - entry_price
    else:  # SHORT
        risk_distance = stop_loss_price - entry_price
        reward_distance = entry_price - take_profit_price

    if risk_distance <= 0:
        return SizeResult(
            position_size=0, position_notional=0, margin_required=0,
            risk_amount=0, leverage_used=0, risk_reward_ratio=0,
            stop_loss_distance_pct=0, valid=False,
            reason=f"Stop loss mal colocado: distancia negativa ({risk_distance:.4f})",
        )

    # ── Ratios ──
    stop_loss_distance_pct = (risk_distance / entry_price) * 100
    rr_ratio = reward_distance / risk_distance if risk_distance > 0 else 0

    # ── Cálculo central ──
    risk_amount = capital * risk_per_trade_pct
    risk_pct_decimal = risk_distance / entry_price
    position_notional = risk_amount / risk_pct_decimal if risk_pct_decimal > 0 else 0
    position_size = position_notional / entry_price if entry_price > 0 else 0

    # ── Leverage check ──
    leverage_used = position_notional / capital if capital > 0 else 0
    
    if leverage_used > max_leverage:
        # Ajustar tamaño para no exceder leverage máximo
        position_notional = capital * max_leverage
        position_size = position_notional / entry_price
        leverage_used = max_leverage
        # Recalcular riesgo con el nuevo tamaño
        risk_amount = position_notional * risk_pct_decimal
        log.warning(
            f"[SIZER] Leverage reducido de {leverage_used:.2f}x a {max_leverage:.1f}x | "
            f"Riesgo ajustado: ${risk_amount:.2f}"
        )

    # ── Min order size check ──
    if position_size < min_order_size:
        return SizeResult(
            position_size=0, position_notional=0, margin_required=0,
            risk_amount=0, leverage_used=0, risk_reward_ratio=rr_ratio,
            stop_loss_distance_pct=stop_loss_distance_pct, valid=False,
            reason=f"Tamaño ({position_size:.6f}) menor al mínimo ({min_order_size})",
        )

    # ── Calcular margen requerido ──
    margin_required = position_notional / max(1.0, leverage_used) if leverage_used > 0 else position_notional

    log.info(
        f"[SIZER] {direction} | Entry: ${entry_price:.2f} | SL: ${stop_loss_price:.2f} ({stop_loss_distance_pct:.2f}%) | "
        f"TP: ${take_profit_price:.2f} | R:R {rr_ratio:.2f} | "
        f"Size: {position_size:.4f} (${position_notional:.2f}) | Risk: ${risk_amount:.2f} | "
        f"Lev: {leverage_used:.2f}x"
    )

    return SizeResult(
        position_size=round(position_size, 6),
        position_notional=round(position_notional, 2),
        margin_required=round(margin_required, 2),
        risk_amount=round(risk_amount, 2),
        leverage_used=round(leverage_used, 2),
        risk_reward_ratio=round(rr_ratio, 2),
        stop_loss_distance_pct=round(stop_loss_distance_pct, 2),
        valid=True,
    )

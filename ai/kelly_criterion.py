"""
╔══════════════════════════════════════════════════════════╗
║   CRITERIO DE KELLY — Position Sizing Matemático          ║
║   Calcula la fracción óptima del capital a arriesgar      ║
║   maximizando crecimiento y minimizando riesgo de ruina.  ║
╚══════════════════════════════════════════════════════════╝

Fórmula de Kelly:
    f* = W - [(1 - W) / R]

Donde:
    W = Win Rate (probabilidad de ganar)
    R = Ratio Ganancia/Pérdida promedio (avg_win / avg_loss)
    f* = Fracción óptima del capital a arriesgar

Se usa "Half Kelly" (f*/2) como práctica estándar profesional
para reducir volatilidad del portafolio sin sacrificar crecimiento.
"""

import logging
import db

log = logging.getLogger("AgenteBot.Kelly")

# ── Límites de seguridad ──
KELLY_MIN = 0.02   # Nunca menos del 2% (evita parálisis)
KELLY_MAX = 0.25   # Nunca más del 25% (evita bancarrota)
MIN_TRADES_REQUIRED = 3  # Mínimo de trades para confiar en la estadística (Aggressive Start)


def get_kelly_stats(days: int = 30) -> dict:
    """
    Extrae Win Rate y Ratio G/P promedio de los últimos N días.
    Retorna None si no hay datos suficientes.
    """
    data = db.get_kelly_data(days)
    if not data or len(data) < MIN_TRADES_REQUIRED:
        return None

    wins = [t for t in data if t["result"] == "win"]
    losses = [t for t in data if t["result"] == "loss"]

    if not wins or not losses:
        return None  # No se puede calcular ratio sin ambos lados

    win_rate = len(wins) / len(data)
    avg_win = sum(abs(t["pnl_pct"]) for t in wins) / len(wins)
    avg_loss = sum(abs(t["pnl_pct"]) for t in losses) / len(losses)

    if avg_loss == 0:
        return None  # División por cero imposible

    ratio = avg_win / avg_loss  # R = promedio ganancia / promedio pérdida

    return {
        "win_rate": win_rate,
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "ratio": ratio,
        "total_trades": len(data),
        "wins": len(wins),
        "losses": len(losses),
    }


def calculate_kelly_fraction(stats: dict = None, days: int = 30) -> float:
    """
    Calcula la fracción óptima de Kelly (Half Kelly).
    Retorna un float entre KELLY_MIN y KELLY_MAX.
    Si no hay datos suficientes, retorna None (usar fallback).
    """
    if stats is None:
        stats = get_kelly_stats(days)

    if stats is None:
        return None  # Datos insuficientes, usar lógica legacy

    W = stats["win_rate"]
    R = stats["ratio"]

    # Fórmula de Kelly: f* = W - [(1 - W) / R]
    full_kelly = W - ((1 - W) / R)

    # Half Kelly: más conservador, reduce drawdowns en ~50%
    half_kelly = full_kelly / 2.0

    # Si Kelly es negativo, el sistema dice "NO OPERES"
    if half_kelly <= 0:
        log.warning(f"[KELLY] Fracción negativa ({full_kelly:.4f}). "
                    f"WR={W:.0%} R={R:.2f}. Sistema no tiene ventaja estadística.")
        return KELLY_MIN  # Mínimo absoluto de supervivencia

    # Clamp entre límites de seguridad
    clamped = max(KELLY_MIN, min(half_kelly, KELLY_MAX))

    log.info(f"[KELLY] f*={full_kelly:.4f} → Half={half_kelly:.4f} → "
             f"Clamped={clamped:.4f} | WR={W:.0%} R={R:.2f} ({stats['total_trades']} trades)")

    return clamped


def get_kelly_risk(b_score: int, regime: str, days: int = 30) -> float:
    """
    Función principal: devuelve el % de riesgo óptimo para un trade.
    Combina Kelly con ajustes por Score y Régimen.
    Retorna None si no hay datos (señal de usar fallback legacy).
    """
    kelly = calculate_kelly_fraction(days=days)

    if kelly is None:
        return None  # Sin datos, el caller usará get_agent_risk() legacy

    # Moduladores contextuales sobre la base de Kelly
    if b_score >= 3 and regime == "BULL":
        modifier = 1.20       # Confianza alta + mercado favorable
    elif b_score >= 3:
        modifier = 1.0        # Confianza alta, mercado neutro
    elif b_score == 2 and regime == "BEAR":
        modifier = 0.50       # Defensivo total
    elif regime == "SIDEWAYS":
        modifier = 0.70       # Precaución lateral
    else:
        modifier = 0.80       # Estándar

    adjusted = kelly * modifier

    # Re-clamp por seguridad después del modificador
    final = max(KELLY_MIN, min(adjusted, KELLY_MAX))

    return final

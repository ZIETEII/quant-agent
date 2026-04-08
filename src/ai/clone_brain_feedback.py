"""
╔══════════════════════════════════════════════════════════╗
║  CLONE BRAIN FEEDBACK — Retroalimentación al Cerebro     ║
║  Cuando un clon termina su ciclo, compara vs el cerebro  ║
║  principal y sugiere/aplica mutaciones de parámetros     ║
╚══════════════════════════════════════════════════════════╝
"""

import json
import logging
from datetime import datetime

from core import db

log = logging.getLogger("AgenteBot.CloneFeedback")

# Umbral mínimo: el clon debe superar al principal por este % para influir
SUPERIORITY_THRESHOLD = 3.0  # +3% más que el principal

# Máximo ajuste de un parámetro por ciclo (para evitar saltos bruscos)
MAX_MUTATION_FACTOR = 0.20   # 20% máximo de cambio


def process_clone_cycle_report(report: dict) -> dict | None:
    """
    Procesa el reporte de fin de ciclo de un clon.
    Compara rendimiento vs el cerebro principal.
    Si el clon fue superior, sugiere mutaciones de parámetros.
    
    Args:
        report: dict generado por BaseClone._generate_cycle_report()
    
    Returns:
        dict con las mutaciones aplicadas, o None si no hubo cambios.
    """
    clone_id = report["clone_id"]
    clone_name = report["clone_name"]
    cycle_days = report["cycle_days"]
    clone_pnl_pct = report["pnl_return_pct"]
    clone_win_rate = report["win_rate"]
    clone_trades = report["total_trades"]
    clone_params = report["params_used"]

    # ── Obtener rendimiento del cerebro principal en el mismo período ──
    main_perf = db.get_main_performance(cycle_days)
    main_pnl_pct = main_perf.get("total_pnl_pct") or 0
    main_win_rate = 0
    main_trades = main_perf.get("total_trades") or 0
    if main_trades > 0:
        main_wins = main_perf.get("wins") or 0
        main_win_rate = (main_wins / main_trades * 100)

    # ── Comparar ──
    delta_pnl = clone_pnl_pct - main_pnl_pct
    delta_wr = clone_win_rate - main_win_rate

    comparison = {
        "clone_id": clone_id,
        "clone_name": clone_name,
        "cycle_number": report["cycle_number"],
        "cycle_days": cycle_days,
        "clone_pnl_pct": clone_pnl_pct,
        "clone_win_rate": clone_win_rate,
        "clone_trades": clone_trades,
        "main_pnl_pct": round(main_pnl_pct, 2),
        "main_win_rate": round(main_win_rate, 1),
        "main_trades": main_trades,
        "delta_pnl": round(delta_pnl, 2),
        "delta_win_rate": round(delta_wr, 1),
        "superior": delta_pnl > SUPERIORITY_THRESHOLD,
    }

    # ── Guardar insight de comparación (siempre) ──
    insight_msg = (
        f"📊 Ciclo #{report['cycle_number']} de {clone_name} completado: "
        f"PnL {clone_pnl_pct:+.1f}% (vs Main {main_pnl_pct:+.1f}%) | "
        f"WR {clone_win_rate:.0f}% | "
        f"Δ = {delta_pnl:+.1f}%"
    )
    db.save_insight("CLONE_CYCLE_REPORT", insight_msg, json.dumps(comparison))

    # ── Si no es superior, no mutar ──
    if not comparison["superior"]:
        log.info(
            f"[{clone_name}] Ciclo #{report['cycle_number']}: "
            f"PnL {clone_pnl_pct:+.1f}% vs Main {main_pnl_pct:+.1f}% — "
            f"No alcanza umbral de +{SUPERIORITY_THRESHOLD}%, sin mutaciones."
        )
        return None

    # ── El clon superó al principal → Calcular mutaciones ──
    if clone_trades < 3:
        log.info(f"[{clone_name}] Superior pero con <3 trades, ignorando.")
        return None

    mutations = _calculate_mutations(clone_params, comparison)

    if mutations:
        _apply_mutations(mutations, clone_name, report["cycle_number"])
        comparison["mutations_applied"] = mutations

    return comparison


def _calculate_mutations(clone_params: dict, comparison: dict) -> dict:
    """
    Calcula qué parámetros del cerebro principal deben mutar
    basándose en los parámetros exitosos del clon.
    """
    mutations = {}

    # Obtener parámetros actuales del cerebro
    try:
        current_params = {}
        with db.get_conn() as conn:
            rows = conn.execute("SELECT key, value FROM agent_params").fetchall()
        for r in rows:
            current_params[r["key"]] = r["value"]
    except:
        return {}

    # Parámetros que el clon puede influenciar
    PARAM_MAP = {
        "RISK_PERCENT": ("RISK_PERCENT", float),
        "TAKE_PROFIT": ("TAKE_PROFIT", float),  # El cerebro no tiene este directamente, 
        "STOP_LOSS": ("STOP_LOSS", float),       # pero lo guardamos como sugerencia
    }

    for clone_key, (brain_key, cast) in PARAM_MAP.items():
        clone_val = clone_params.get(clone_key)
        if clone_val is None:
            continue

        brain_val_str = current_params.get(brain_key)
        if brain_val_str is None:
            continue

        try:
            brain_val = cast(brain_val_str)
            clone_val = cast(clone_val)
        except:
            continue

        if brain_val == 0:
            continue

        # Calcular el ajuste: mover el cerebro un 30% hacia el valor del clon
        diff = clone_val - brain_val
        adjustment = diff * 0.30  # Paso conservador

        # Limitar ajuste máximo
        max_change = brain_val * MAX_MUTATION_FACTOR
        adjustment = max(-max_change, min(max_change, adjustment))

        new_val = brain_val + adjustment

        if abs(adjustment) > 0.001:  # Solo si hay cambio significativo
            mutations[brain_key] = {
                "old": round(brain_val, 4),
                "new": round(new_val, 4),
                "clone_val": round(clone_val, 4),
                "adjustment": round(adjustment, 4),
            }

    return mutations


def _apply_mutations(mutations: dict, clone_name: str, cycle_number: int):
    """Aplica las mutaciones calculadas a los parámetros del cerebro."""
    for param_key, change in mutations.items():
        reason = (
            f"Mutación vía {clone_name} ciclo #{cycle_number}: "
            f"{change['old']} → {change['new']} "
            f"(clon usó {change['clone_val']})"
        )

        try:
            with db.get_conn() as conn:
                conn.execute(
                    "UPDATE agent_params SET value=?, reason=?, "
                    "updated_at=datetime('now','localtime') WHERE key=?",
                    (str(change["new"]), reason, param_key)
                )
                conn.commit()
            log.info(f"[MUTACIÓN] {param_key}: {change['old']} → {change['new']} ({reason})")
        except Exception as e:
            log.error(f"[MUTACIÓN] Error aplicando {param_key}: {e}")

    # Guardar insight de mutación
    db.save_insight(
        "PARAM_ADJUST",
        f"🧬 Mutación genética del cerebro por {clone_name} (ciclo #{cycle_number}): "
        f"{len(mutations)} parámetros ajustados",
        json.dumps(mutations)
    )

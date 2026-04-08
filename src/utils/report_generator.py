"""
╔══════════════════════════════════════════════════════════╗
║   GENERADOR DE REPORTES DIARIOS — report_generator.py    ║
║   Genera un reporte .md detallado cada 24h a las 8 AM    ║
║   Guardado automático en docs/reportes/                  ║
╚══════════════════════════════════════════════════════════╝
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta

REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "reportes")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quant_memory.db")


def generate_daily_report(app_state: dict = None) -> str:
    """Genera un reporte .md completo y lo guarda en docs/reportes/."""
    os.makedirs(REPORTS_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # ── Estado del agente ──
    state_rows = dict(conn.execute("SELECT key, value FROM agent_state").fetchall())
    balance = float(state_rows.get("balance", 0))
    total_pnl = float(state_rows.get("total_pnl", 0))
    win_count = int(state_rows.get("win_count", 0))
    closed_count = int(state_rows.get("closed_count", 0))
    loss_count = closed_count - win_count

    active_trades = json.loads(state_rows.get("active_trades", "[]"))
    active_investment = sum(t.get("entry", 0) * t.get("qty", 0) for t in active_trades)
    total_equity = balance + active_investment + sum(t.get("pnl", 0) for t in active_trades)

    # ── Historial de trades ──
    all_trades = conn.execute(
        "SELECT symbol, entry_price, exit_price, pnl, pnl_pct, result, reason, "
        "market_regime, opened_at, closed_at FROM trades ORDER BY closed_at DESC"
    ).fetchall()

    # Trades de las últimas 24h
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    recent_trades = [t for t in all_trades if (t["closed_at"] or "") >= cutoff]

    # ── Parámetros adaptativos ──
    params = dict(conn.execute("SELECT key, value FROM agent_params").fetchall())

    # ── Calcular métricas ──
    win_rate = (win_count / closed_count * 100) if closed_count > 0 else 0
    recent_wins = sum(1 for t in recent_trades if t["result"] == "win")
    recent_losses = len(recent_trades) - recent_wins
    recent_pnl = sum(t["pnl"] for t in recent_trades)
    recent_wr = (recent_wins / len(recent_trades) * 100) if recent_trades else 0

    # Mejor y peor trade del periodo
    best_trade = max(recent_trades, key=lambda t: t["pnl"]) if recent_trades else None
    worst_trade = min(recent_trades, key=lambda t: t["pnl"]) if recent_trades else None

    # Trades por moneda
    symbol_stats = {}
    for t in recent_trades:
        sym = t["symbol"]
        if sym not in symbol_stats:
            symbol_stats[sym] = {"wins": 0, "losses": 0, "pnl": 0.0, "trades": 0}
        symbol_stats[sym]["trades"] += 1
        symbol_stats[sym]["pnl"] += t["pnl"]
        if t["result"] == "win":
            symbol_stats[sym]["wins"] += 1
        else:
            symbol_stats[sym]["losses"] += 1

    # Razones de cierre
    reason_counts = {}
    for t in recent_trades:
        r = t["reason"]
        reason_counts[r] = reason_counts.get(r, 0) + 1

    # ── Estado del ML / Memoria ──
    try:
        total_closed = conn.execute("SELECT COUNT(*) FROM trades WHERE result IS NOT NULL").fetchone()[0]
    except:
        total_closed = len(all_trades)
    
    ml_model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "agent_model.pkl")
    ml_is_trained = os.path.exists(ml_model_path)
    trades_needed = 30
    ml_progress = min(total_closed / trades_needed * 100, 100)

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    # ── Construir el reporte ──
    lines = []
    lines.append(f"# 📊 Reporte Diario — Quant Agent AI")
    lines.append(f"**Fecha:** {date_str} | **Generado a las:** {time_str}")
    lines.append(f"**Periodo cubierto:** Últimas 24 horas")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Resumen ejecutivo
    lines.append("## 💰 Resumen Ejecutivo")
    lines.append("")
    lines.append("| Métrica | Valor |")
    lines.append("|---------|-------|")
    lines.append(f"| **Total Equity** | **${total_equity:.2f}** |")
    lines.append(f"| Balance Libre | ${balance:.2f} |")
    lines.append(f"| En Inversión | ${active_investment:.2f} ({len(active_trades)} pos. abiertas) |")
    lines.append(f"| PnL Realizado (total) | ${total_pnl:+.4f} |")
    lines.append(f"| PnL Últimas 24h | **${recent_pnl:+.4f}** |")
    lines.append(f"| Win Rate (global) | {win_rate:.1f}% ({win_count}W / {loss_count}L) |")
    lines.append(f"| Win Rate (24h) | {recent_wr:.1f}% ({recent_wins}W / {recent_losses}L) |")
    lines.append(f"| Total Trades Cerrados | {closed_count} |")
    lines.append(f"| Trades en 24h | {len(recent_trades)} |")
    lines.append("")

    # Posiciones activas
    lines.append("---")
    lines.append("")
    lines.append("## 🔓 Posiciones Activas")
    lines.append("")
    if active_trades:
        lines.append("| Par | Entrada | Qty | Inversión | PnL Flotante |")
        lines.append("|-----|---------|-----|-----------|-------------|")
        for t in active_trades:
            inv = t.get("entry", 0) * t.get("qty", 0)
            pnl = t.get("pnl", 0)
            pnl_pct = t.get("pnl_pct", 0)
            icon = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"| {t['symbol']} | ${t['entry']:.6f} | {t.get('qty',0):.4f} | ${inv:.2f} | {icon} ${pnl:+.4f} ({pnl_pct:+.2f}%) |")
    else:
        lines.append("*Sin posiciones abiertas*")
    lines.append("")

    # Historial 24h
    lines.append("---")
    lines.append("")
    lines.append("## 📋 Trades Cerrados (Últimas 24h)")
    lines.append("")
    if recent_trades:
        lines.append("| # | Par | Resultado | PnL | PnL % | Razón | Régimen | Duración |")
        lines.append("|---|-----|-----------|-----|-------|-------|---------|----------|")
        for i, t in enumerate(recent_trades, 1):
            icon = "✅" if t["result"] == "win" else "❌"
            # Calcular duración
            try:
                opened = datetime.fromisoformat(t["opened_at"])
                closed_str = t["closed_at"].replace(" ", "T") if " " in t["closed_at"] else t["closed_at"]
                closed = datetime.fromisoformat(closed_str.split(".")[0])
                dur = (closed - opened).total_seconds() / 3600
                dur_str = f"{dur:.1f}h"
            except:
                dur_str = "—"
            lines.append(f"| {i} | {t['symbol']} | {icon} | ${t['pnl']:+.4f} | {t['pnl_pct']:+.2f}% | {t['reason']} | {t['market_regime']} | {dur_str} |")
    else:
        lines.append("*Sin trades cerrados en las últimas 24 horas*")
    lines.append("")

    # Mejor/peor trade
    if best_trade or worst_trade:
        lines.append("---")
        lines.append("")
        lines.append("## ⚡ Highlights")
        lines.append("")
        if best_trade:
            lines.append(f"- 🏆 **Mejor trade:** {best_trade['symbol']} → **{best_trade['pnl_pct']:+.2f}%** (${best_trade['pnl']:+.4f}) via {best_trade['reason']}")
        if worst_trade:
            lines.append(f"- 💀 **Peor trade:** {worst_trade['symbol']} → **{worst_trade['pnl_pct']:+.2f}%** (${worst_trade['pnl']:+.4f}) via {worst_trade['reason']}")
        lines.append("")

    # Rendimiento por moneda
    if symbol_stats:
        lines.append("---")
        lines.append("")
        lines.append("## 🏦 Rendimiento por Moneda (24h)")
        lines.append("")
        lines.append("| Par | Trades | Wins | Losses | PnL Total |")
        lines.append("|-----|--------|------|--------|-----------|")
        for sym, s in sorted(symbol_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
            icon = "🟢" if s["pnl"] >= 0 else "🔴"
            lines.append(f"| {sym} | {s['trades']} | {s['wins']} | {s['losses']} | {icon} ${s['pnl']:+.4f} |")
        lines.append("")

    # Razones de cierre
    if reason_counts:
        lines.append("---")
        lines.append("")
        lines.append("## 🔧 Razones de Cierre")
        lines.append("")
        lines.append("| Razón | Cantidad |")
        lines.append("|-------|----------|")
        for reason, count in sorted(reason_counts.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"| {reason} | {count} |")
        lines.append("")

    # Parámetros
    lines.append("---")
    lines.append("")
    lines.append("## ⚙️ Parámetros del Agente")
    lines.append("")
    lines.append("| Parámetro | Valor |")
    lines.append("|-----------|-------|")
    for k, v in params.items():
        lines.append(f"| {k} | {v} |")
    lines.append("")

    # Estado del ML
    lines.append("---")
    lines.append("")
    lines.append("## 🧠 Estado de la Memoria ML (Inteligencia Artificial)")
    lines.append("")
    if ml_is_trained:
        lines.append(f"✅ **Bucle de Aprendizaje Activo:** El modelo predictivo Random Forest está entrenado y filtrando operaciones en tiempo real.")
        lines.append(f"- **Memoria acumulada:** {total_closed} trades de experiencia.")
        lines.append(f"- Las decisiones predictivas ya se aplican para descartar operaciones con menos del 50% de probabilidad de éxito.")
    else:
        lines.append(f"⏳ **Bucle de Aprendizaje Autónomo - Fase de Recolección:**")
        lines.append(f"- **Progreso de entrenamiento inicial:** {ml_progress:.1f}% ({total_closed}/{trades_needed} trades cerrados).")
        lines.append(f"- El agente está aprendiendo de cada operación (ganada o perdida). Se requiere llegar a 30 trades para inicializar el peso sináptico del Random Forest.\n")
    
    lines.append("**📡 Variables Neuronales Almacenadas en Memoria:**")
    lines.append("Por cada trade, el agente está registrando y memorizando su contexto para tomar decisiones futuras:")
    lines.append("1. `RSI_at_entry`: Fuerza relativa al momento de compra.")
    lines.append("2. `MACD_at_entry`: Momentum del cruce del MACD.")
    lines.append("3. `TF_score`: Fuerzas concurrentes (15m, 30m, 1h).")
    lines.append("4. `EMA_alignment`: Conformación de mediano vs largo plazo.")
    lines.append("5. `Market_Regime`: El entorno global (BULL/BEAR) en el que se hizo la compra.")
    lines.append("")

    # Estado Multi-Agente (Clones)
    lines.append("---")
    lines.append("")
    lines.append("## 🧬 Ecosistema Multi-Agente (Clones OOP)")
    lines.append("")
    try:
        import sys
        if "bot_agente" in sys.modules:
            clone_instances = sys.modules["bot_agente"].clone_instances
        else:
            from bot_agente import clone_instances
            
        if clone_instances:
            lines.append("| Clon | Balance (Virtual) | Trades Activos | PnL Histórico | Win Rate |")
            lines.append("|------|-------------------|----------------|---------------|----------|")
            for cid, c in clone_instances.items():
                c_wr = (c.win_count / c.closed_count * 100) if c.closed_count > 0 else 0
                lines.append(f"| **{c.name}** | ${c.balance:.2f} | {len(c.active_trades)} | ${c.total_pnl:+.4f} | {c_wr:.1f}% |")
        else:
            lines.append("*Sin clones activos.*")
    except Exception as e:
        lines.append(f"*Error obteniendo estado de clones: {e}*")
    lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"*Reporte generado automáticamente por Quant Agent AI — {now.strftime('%Y-%m-%d %H:%M:%S')}*")

    report_content = "\n".join(lines)

    # ── Guardar ──
    filename = f"reporte_{date_str}.md"
    filepath = os.path.join(REPORTS_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_content)

    conn.close()
    return filepath


if __name__ == "__main__":
    path = generate_daily_report()
    print(f"Reporte guardado en: {path}")

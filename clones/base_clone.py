"""
╔══════════════════════════════════════════════════════════╗
║   BASE CLONE — Shadow Trading Engine (Solana DEX)        ║
║   Cada clon copia las entradas del agente principal       ║
║   con sus propios parámetros + MEMORIA PERSISTENTE       ║
║   + CICLOS DE VIDA + REPORTES AL CEREBRO                 ║
╚══════════════════════════════════════════════════════════╝
"""
import time
import json
import logging
from datetime import datetime, timedelta
import copy

import db
from ai.sentiment import get_risk_modifier

log = logging.getLogger("AgenteBot.Clone")


class BaseClone:
    """
    Shadow Trader con memoria persistente y ciclos de vida.
    
    Cada clon:
    - Copia trades del agente principal con su propio perfil de riesgo
    - Persiste su estado en SQLite (sobrevive reinicios)
    - Tiene un ciclo de vida (15/30/90 días)
    - Al terminar el ciclo, genera reporte para el cerebro principal
    """

    def __init__(self, agent_id: str, name: str, params: dict):
        self.agent_id = agent_id
        self.name = name
        self.params = params
        self.initial_balance = params.get("INITIAL_BALANCE", 10000.0)
        self.cycle_days = params.get("CYCLE_DAYS", 30)

        # Estado volátil (se carga desde DB si existe)
        self.balance = self.initial_balance
        self.active_trades = []
        self.total_pnl = 0.0
        self.win_count = 0
        self.closed_count = 0
        self.unrealized_pnl = 0.0
        self._synced_mints = set()
        self.cycle_number = 1
        self.cycle_start = datetime.now().isoformat()

        # Tracking de trades cerrados en el ciclo actual (para reportes)
        self._cycle_closed_trades = []

        # Cargar estado persistido
        self._load_from_db()

    # ══════════════════════════════════════════════════════════
    #  💾 PERSISTENCIA
    # ══════════════════════════════════════════════════════════

    def _load_from_db(self):
        """Restaura estado desde SQLite al iniciar."""
        try:
            state = db.load_clone_state(self.agent_id)
            if state:
                self.balance = state["balance"]
                self.total_pnl = state["total_pnl"]
                self.win_count = state["win_count"]
                self.closed_count = state["closed_count"]
                self.cycle_number = state.get("cycle_number", 1)
                self.cycle_start = state.get("cycle_start", datetime.now().isoformat())
                self._synced_mints = set(state.get("synced_mints", []))
                self.active_trades = state.get("active_trades", [])
                log.info(
                    f"[{self.name}] Estado restaurado: "
                    f"Balance=${self.balance:.2f} | PnL=${self.total_pnl:.2f} | "
                    f"Ciclo #{self.cycle_number} (día {self._days_in_cycle()}/{self.cycle_days})"
                )
            else:
                log.info(f"[{self.name}] Sin estado previo — iniciando ciclo #1 fresco")
                self._save_to_db()
        except Exception as e:
            log.warning(f"[{self.name}] Error cargando estado: {e}")

    def _save_to_db(self):
        """Persiste estado actual a SQLite."""
        try:
            # Serializar active_trades (limpiar objetos no serializables)
            trades_clean = []
            for t in self.active_trades:
                tc = {k: v for k, v in t.items() if isinstance(v, (str, int, float, bool, type(None), list, dict))}
                trades_clean.append(tc)

            db.save_clone_state(
                clone_id=self.agent_id,
                balance=self.balance,
                total_pnl=self.total_pnl,
                win_count=self.win_count,
                closed_count=self.closed_count,
                cycle_number=self.cycle_number,
                cycle_start=self.cycle_start,
                cycle_days=self.cycle_days,
                synced_mints=list(self._synced_mints),
                active_trades=trades_clean,
            )
        except Exception as e:
            log.error(f"[{self.name}] Error guardando estado: {e}")

    def _days_in_cycle(self) -> int:
        """Días transcurridos en el ciclo actual."""
        try:
            start = datetime.fromisoformat(self.cycle_start)
            return (datetime.now() - start).days
        except:
            return 0

    # ══════════════════════════════════════════════════════════
    #  📊 ESTADO
    # ══════════════════════════════════════════════════════════

    def get_state(self) -> dict:
        days_in = self._days_in_cycle()
        days_remaining = max(0, self.cycle_days - days_in)
        
        # Extraer filtros de entrada propios del clon
        entry_filters = {}
        for key in ("MIN_MOMENTUM", "MIN_SAFETY", "MIN_TOTAL_SCORE", "MIN_TREND_MINUTES"):
            if key in self.params:
                entry_filters[key] = self.params[key]
        
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "balance": round(self.balance, 4),
            "initial_balance": self.initial_balance,
            "active_trades": self.active_trades,
            "total_pnl": round(self.total_pnl, 4),
            "win_count": self.win_count,
            "closed_count": self.closed_count,
            "unrealized_pnl": round(self.unrealized_pnl, 4),
            "win_rate": round(self.win_count / self.closed_count * 100, 1) if self.closed_count else 0.0,
            # Ciclo
            "cycle_number": self.cycle_number,
            "cycle_days": self.cycle_days,
            "cycle_start": self.cycle_start,
            "days_in_cycle": days_in,
            "days_remaining": days_remaining,
            "cycle_progress": round(min(1.0, days_in / self.cycle_days) * 100, 1),
            # Filtros de entrada (ADN del clon)
            "entry_filters": entry_filters,
        }

    # ══════════════════════════════════════════════════════════
    #  🧬 FILTRO DE ENTRADA — Overridable por cada clon
    # ══════════════════════════════════════════════════════════

    def should_enter(self, trade: dict) -> bool:
        """
        Filtro inteligente de entrada — cada clon lo sobrescribe
        con su propia lógica de selección.

        Args:
            trade: Dict del trade del agente principal con campos:
                - scores: {momentum, safety, total, timing}
                - source: "bluechip" | "trending" | "new_pair" | "new_profile" | "boosted"
                - opened_at: ISO timestamp
                - symbol, mint, entry_usd, etc.

        Returns:
            True si el clon debe copiar este trade, False si lo rechaza.
            
        Override en subclases para lógica especializada.
        Por defecto acepta todo (comportamiento legacy).
        """
        return True

    def _get_rejection_reason(self, trade: dict) -> str:
        """Override en subclases para dar razón específica del rechazo."""
        return "filtro genérico"

    # ══════════════════════════════════════════════════════════
    #  🔄 SYNC: Copiar entradas del agente principal
    # ══════════════════════════════════════════════════════════

    def sync_entries(self, main_trades: list, sol_price_usd: float):
        """
        Copia nuevos trades del agente principal aplicando:
        1. Filtro de entrada inteligente (should_enter) — ADN del clon
        2. Perfil de riesgo del clon (position sizing, TP/SL, trailing)
        Solo copia trades que aún no hemos procesado.
        """
        new_entries = False
        for trade in main_trades:
            mint = trade["mint"]
            if mint in self._synced_mints:
                continue
            if len(self.active_trades) >= self.params.get("MAX_TRADES", 6):
                continue

            entry_usd = trade.get("entry_usd", trade.get("price_usd", 0))
            if entry_usd <= 0:
                continue

            # ── 🧬 FILTRO DE ADN — ¿Este trade encaja con mi perfil? ──
            if not self.should_enter(trade):
                self._synced_mints.add(mint)  # marcar como visto para no re-evaluar
                log.debug(
                    f"[{self.name}] ✕ Rechazó {trade.get('symbol', '?')} — "
                    f"{self._get_rejection_reason(trade)}"
                )
                continue

            # ── 🛡️ DEFENSA MACROECONÓMICA ──
            # Se multiplica riesgo base por el modificador de sentimiento global
            risk_pct = self.params.get("RISK_PERCENT", 0.10) * get_risk_modifier()
            invest_usd = self.balance * risk_pct
            if invest_usd < 0.50:
                continue

            qty = invest_usd / entry_usd

            tp_pct = self.params.get("TAKE_PROFIT", 15)
            sl_pct = self.params.get("STOP_LOSS", 8)
            trailing = self.params.get("TRAILING", 5)

            clone_trade = {
                "mint": mint,
                "symbol": trade.get("symbol", "?"),
                "name": trade.get("name", "Unknown"),
                "entry_usd": entry_usd,
                "qty": qty,
                "sol_spent": invest_usd / sol_price_usd if sol_price_usd > 0 else 0,
                "sl_pct": sl_pct,
                "tp_pct": tp_pct,
                "trailing_pct": trailing,
                "dead_trade_min": self.params.get("DEAD_TRADE_MIN", 45),
                "moonbag_pct": self.params.get("MOONBAG", 0),
                "sl_price": entry_usd * (1 - sl_pct / 100),
                "tp_price": entry_usd * (1 + tp_pct / 100),
                "highest_price": entry_usd,
                "trailing_active": False,
                "current_price": entry_usd,
                "pnl": 0.0,
                "pnl_pct": 0.0,
                "opened_at": trade.get("opened_at", datetime.now().isoformat()),
                "agent_id": self.agent_id,
                "source": trade.get("source", "shadow"),
                "scores": trade.get("scores", {}),
                "type": "BUY",
                "symbol_display": trade.get("symbol_display", trade.get("symbol", "?")),
                "entry": entry_usd,
                "sl": entry_usd * (1 - sl_pct / 100),
                "tp2": entry_usd * (1 + tp_pct / 100),
            }

            self.active_trades.append(clone_trade)
            self.balance -= invest_usd
            self._synced_mints.add(mint)
            new_entries = True
            log.info(
                f"[{self.name}] ✓ Entró {trade.get('symbol', '?')} | "
                f"Scores: M:{trade.get('scores',{}).get('momentum',0):.0f} "
                f"S:{trade.get('scores',{}).get('safety',0):.0f} | "
                f"Source: {trade.get('source','?')}"
            )

        if new_entries:
            self._save_to_db()

    # ══════════════════════════════════════════════════════════
    #  📊 UPDATE: Actualizar precios y gestionar exits
    # ══════════════════════════════════════════════════════════

    def update_prices(self, prices: dict, sol_price_usd: float):
        """
        Actualiza precios de posiciones abiertas y ejecuta lógica de exits.
        """
        trades_to_close = []
        total_unrealized = 0.0

        for trade in self.active_trades:
            mint = trade["mint"]
            current_price = prices.get(mint, trade.get("current_price", trade["entry_usd"]))

            if current_price <= 0:
                continue

            trade["current_price"] = current_price
            entry = trade["entry_usd"]
            pnl_pct = ((current_price - entry) / entry * 100) if entry > 0 else 0
            pnl_usd = (current_price - entry) * trade["qty"]
            trade["pnl"] = round(pnl_usd, 6)
            trade["pnl_pct"] = round(pnl_pct, 2)
            total_unrealized += pnl_usd

            if current_price > trade.get("highest_price", entry):
                trade["highest_price"] = current_price

            trade["sl"] = trade.get("sl_price", entry * (1 - trade["sl_pct"] / 100))
            trade["tp2"] = trade.get("tp_price", entry * (1 + trade["tp_pct"] / 100))

            # ── STOP LOSS ──
            if pnl_pct <= -trade["sl_pct"]:
                trades_to_close.append((trade, "STOP_LOSS", pnl_usd, pnl_pct))
                continue

            # ── TAKE PROFIT → Activate trailing ──
            if pnl_pct >= trade["tp_pct"]:
                if not trade.get("tp_hit", False):
                    trade["tp_hit"] = True
                    trade["trailing_active"] = True

            # ── TRAILING STOP ──
            if trade.get("trailing_active", False):
                highest = trade.get("highest_price", entry)
                drop = ((highest - current_price) / highest * 100) if highest > 0 else 0
                if drop >= trade["trailing_pct"]:
                    trades_to_close.append((trade, "TRAILING_STOP", pnl_usd, pnl_pct))
                    continue

            # ── DEAD TRADE ──
            try:
                opened = datetime.fromisoformat(trade["opened_at"])
                age_min = (datetime.now() - opened).total_seconds() / 60
                if age_min >= trade.get("dead_trade_min", 45) and abs(pnl_pct) < 3:
                    trades_to_close.append((trade, "DEAD_TRADE", pnl_usd, pnl_pct))
                    continue
            except:
                pass

        self.unrealized_pnl = round(total_unrealized, 4)

        # ── Execute closes ──
        state_changed = len(trades_to_close) > 0
        for trade, reason, pnl_usd, pnl_pct in trades_to_close:
            is_win = pnl_pct > 0
            sell_value = trade["qty"] * trade["current_price"]

            self.balance += sell_value
            self.total_pnl += pnl_usd
            self.closed_count += 1
            if is_win:
                self.win_count += 1

            # Guardar en historial del ciclo
            self._cycle_closed_trades.append({
                "symbol": trade.get("symbol", "?"),
                "pnl_pct": pnl_pct,
                "pnl_usd": pnl_usd,
                "reason": reason,
                "result": "win" if is_win else "loss",
            })

            self.active_trades.remove(trade)
            self._synced_mints.discard(trade["mint"])

        if state_changed:
            self._save_to_db()

        return trades_to_close

    # ══════════════════════════════════════════════════════════
    #  🔄 CICLO DE VIDA
    # ══════════════════════════════════════════════════════════

    def check_cycle(self) -> dict | None:
        """
        Verifica si el ciclo actual ha terminado.
        Si terminó: genera reporte, guarda ciclo, reinicia.
        Retorna el reporte del ciclo si terminó, None si no.
        """
        days_in = self._days_in_cycle()
        if days_in < self.cycle_days:
            return None

        # ── Ciclo terminado ──
        log.info(f"[{self.name}] ¡Ciclo #{self.cycle_number} completado! ({self.cycle_days} días)")

        report = self._generate_cycle_report()

        # Guardar ciclo en DB
        try:
            db.save_clone_cycle(
                clone_id=self.agent_id,
                cycle_number=self.cycle_number,
                cycle_start=self.cycle_start,
                cycle_end=datetime.now().isoformat(),
                cycle_days=self.cycle_days,
                initial_balance=self.initial_balance,
                final_balance=self.balance,
                total_pnl=self.total_pnl,
                total_trades=self.closed_count,
                wins=self.win_count,
                losses=self.closed_count - self.win_count,
                win_rate=report["win_rate"],
                avg_pnl=report["avg_pnl_per_trade"],
                best_pct=report["best_trade_pct"],
                worst_pct=report["worst_trade_pct"],
                report_json=json.dumps(report),
            )
        except Exception as e:
            log.error(f"[{self.name}] Error guardando ciclo: {e}")

        # Reiniciar para nuevo ciclo
        self.cycle_number += 1
        self.balance = self.initial_balance
        self.total_pnl = 0.0
        self.win_count = 0
        self.closed_count = 0
        self.unrealized_pnl = 0.0
        self.active_trades = []
        self._synced_mints = set()
        self._cycle_closed_trades = []
        self.cycle_start = datetime.now().isoformat()

        self._save_to_db()

        return report

    def _generate_cycle_report(self) -> dict:
        """Genera reporte detallado del ciclo para el cerebro."""
        pnl_return = ((self.balance - self.initial_balance) / self.initial_balance * 100)
        win_rate = (self.win_count / self.closed_count * 100) if self.closed_count else 0
        avg_pnl = (self.total_pnl / self.closed_count) if self.closed_count else 0

        # Best/worst trades del ciclo
        best_pct = 0.0
        worst_pct = 0.0
        if self._cycle_closed_trades:
            pcts = [t["pnl_pct"] for t in self._cycle_closed_trades]
            best_pct = max(pcts)
            worst_pct = min(pcts)

        # Análisis por razón de cierre
        reason_stats = {}
        for t in self._cycle_closed_trades:
            r = t.get("reason", "UNKNOWN")
            if r not in reason_stats:
                reason_stats[r] = {"count": 0, "pnl": 0.0, "wins": 0}
            reason_stats[r]["count"] += 1
            reason_stats[r]["pnl"] += t.get("pnl_pct", 0)
            if t.get("result") == "win":
                reason_stats[r]["wins"] += 1

        report = {
            "clone_id": self.agent_id,
            "clone_name": self.name,
            "cycle_number": self.cycle_number,
            "cycle_days": self.cycle_days,
            "cycle_start": self.cycle_start,
            "cycle_end": datetime.now().isoformat(),
            # Performance
            "initial_balance": self.initial_balance,
            "final_balance": round(self.balance, 4),
            "pnl_return_pct": round(pnl_return, 2),
            "total_pnl_usd": round(self.total_pnl, 4),
            "total_trades": self.closed_count,
            "wins": self.win_count,
            "losses": self.closed_count - self.win_count,
            "win_rate": round(win_rate, 1),
            "avg_pnl_per_trade": round(avg_pnl, 4),
            "best_trade_pct": round(best_pct, 2),
            "worst_trade_pct": round(worst_pct, 2),
            # Parámetros usados
            "params_used": {
                "RISK_PERCENT": self.params.get("RISK_PERCENT"),
                "TAKE_PROFIT": self.params.get("TAKE_PROFIT"),
                "STOP_LOSS": self.params.get("STOP_LOSS"),
                "TRAILING": self.params.get("TRAILING"),
                "DEAD_TRADE_MIN": self.params.get("DEAD_TRADE_MIN"),
                "MOONBAG": self.params.get("MOONBAG"),
            },
            # Breakdown por razón
            "reason_breakdown": reason_stats,
            # Trade history
            "trades": self._cycle_closed_trades[-50:],  # últimos 50
        }

        return report

    def reset(self, initial_balance: float = None):
        """Reset completo del clon."""
        self.balance = initial_balance or self.initial_balance
        self.active_trades = []
        self.total_pnl = 0.0
        self.win_count = 0
        self.closed_count = 0
        self.unrealized_pnl = 0.0
        self._synced_mints = set()
        self._cycle_closed_trades = []
        self._save_to_db()

"""
╔══════════════════════════════════════════════════════════╗
║  CLONE SIGNALS — Sistema de Señales en Tiempo Real       ║
║  Los clones envían señales al cerebro cada 5 segundos    ║
║  para que tome decisiones más rápido                     ║
╚══════════════════════════════════════════════════════════╝

Tipos de señales:
  → DISCOVERY  : Clon encontró un token que pasó su filtro ADN
  → HOT_TRADE  : Token del clon subio >5% en < 3 min
  → CONVICTION : >= 2 clones compraron el mismo token
  → EXIT_WARN  : Clon cerró por trailing/SL (alerta de salida)
  → ALPHA       : Clon tiene mejor PnL que el cerebro (mutación rápida)
"""

import time
import logging
from collections import defaultdict
from datetime import datetime

log = logging.getLogger("AgenteBot.CloneSignals")


class CloneSignalBus:
    """
    Bus de señales en tiempo real entre clones y cerebro.
    Se ejecuta cada ciclo del scanner (5s).
    """

    def __init__(self):
        # Señales pendientes para el cerebro
        self._signals: list[dict] = []
        # Historial reciente (últimas 100 señales)
        self._history: list[dict] = []
        # Tracking de entradas de clones por mint
        self._clone_entries: dict[str, set] = defaultdict(set)
        # Tokens que el cerebro ya procesó (evitar duplicados)
        self._processed_discoveries: set[str] = set()
        # Último snapshot de PnL por clon
        self._last_pnl: dict[str, float] = {}
        # Umbral de alpha PnL (si clon supera cerebro por este %)
        self.ALPHA_THRESHOLD = 2.0
        # Umbral de hot trade (subida % rápida)
        self.HOT_THRESHOLD = 5.0
        # Tiempo máximo para señal hot (segundos)
        self.HOT_WINDOW = 180  # 3 minutos

    def emit(self, signal_type: str, source: str, data: dict):
        """Emite una señal al bus."""
        signal = {
            "type": signal_type,
            "source": source,
            "data": data,
            "timestamp": time.time(),
            "ts_iso": datetime.now().isoformat(),
        }
        self._signals.append(signal)
        self._history.append(signal)
        # Mantener historial limitado
        if len(self._history) > 100:
            self._history = self._history[-100:]
        return signal

    def drain(self) -> list[dict]:
        """Retorna y limpia todas las señales pendientes."""
        signals = self._signals.copy()
        self._signals.clear()
        return signals

    def peek(self) -> list[dict]:
        """Ver señales sin drenar."""
        return self._signals.copy()

    @property
    def history(self) -> list[dict]:
        return self._history.copy()

    # ══════════════════════════════════════════════════════════
    #  📡 ANÁLISIS EN TIEMPO REAL (llamar cada 5s)
    # ══════════════════════════════════════════════════════════

    def analyze_clones(self, clone_instances: dict, brain_state: dict):
        """
        Analiza el estado de todos los clones y genera señales.
        Llamar en cada iteración del scanner (cada 5s).
        """
        brain_pnl_pct = 0.0
        init_bal = brain_state.get("initial_balance", 1000)
        if init_bal > 0:
            current_bal = brain_state.get("balance_usd", init_bal) + brain_state.get("unrealized_pnl", 0)
            brain_pnl_pct = ((current_bal - init_bal) / init_bal) * 100

        brain_mints = set(t.get("mint") for t in brain_state.get("active_trades", []))

        for cid, clone in clone_instances.items():
            state = clone.get_state()

            # ── SIGNAL: DISCOVERY (clone entró en algo que el cerebro no tiene) ──
            for trade in clone.active_trades:
                mint = trade.get("mint")
                if not mint:
                    continue

                # Registrar entrada del clon
                self._clone_entries[mint].add(cid)

                # Si cerebro no tiene este mint y no lo hemos reportado
                if mint not in brain_mints and mint not in self._processed_discoveries:
                    self.emit("DISCOVERY", cid, {
                        "mint": mint,
                        "symbol": trade.get("symbol", "?"),
                        "entry_usd": trade.get("entry_usd", 0),
                        "clone_name": clone.name,
                        "scores": trade.get("scores", {}),
                        "source": trade.get("source", "?"),
                    })
                    self._processed_discoveries.add(mint)
                    log.info(
                        f"📡 [SIGNAL:DISCOVERY] {clone.name} descubrió "
                        f"{trade.get('symbol', '?')} — cerebro no tiene esta posición"
                    )

                # ── SIGNAL: HOT_TRADE (subida rápida) ──
                pnl_pct = trade.get("pnl_pct", 0)
                opened_at = trade.get("opened_at", "")
                if pnl_pct >= self.HOT_THRESHOLD and opened_at:
                    try:
                        opened_time = datetime.fromisoformat(opened_at)
                        elapsed = (datetime.now() - opened_time).total_seconds()
                        if elapsed <= self.HOT_WINDOW:
                            sig_key = f"hot_{mint}_{cid}"
                            if sig_key not in self._processed_discoveries:
                                self.emit("HOT_TRADE", cid, {
                                    "mint": mint,
                                    "symbol": trade.get("symbol", "?"),
                                    "pnl_pct": round(pnl_pct, 2),
                                    "elapsed_sec": round(elapsed),
                                    "clone_name": clone.name,
                                })
                                self._processed_discoveries.add(sig_key)
                                log.info(
                                    f"🔥 [SIGNAL:HOT] {clone.name} → "
                                    f"{trade.get('symbol', '?')} +{pnl_pct:.1f}% en {elapsed:.0f}s!"
                                )
                    except:
                        pass

                # ── SIGNAL: CONVICTION (2+ clones en el mismo token) ──
                clone_count = len(self._clone_entries.get(mint, set()))
                if clone_count >= 2:
                    sig_key = f"conv_{mint}"
                    if sig_key not in self._processed_discoveries:
                        self.emit("CONVICTION", "multi", {
                            "mint": mint,
                            "symbol": trade.get("symbol", "?"),
                            "clone_count": clone_count,
                            "clones": list(self._clone_entries[mint]),
                        })
                        self._processed_discoveries.add(sig_key)
                        log.info(
                            f"🎯 [SIGNAL:CONVICTION] {clone_count} clones "
                            f"compraron {trade.get('symbol', '?')} — señal fuerte!"
                        )

            # ── SIGNAL: ALPHA (clon supera al cerebro) ──
            clone_pnl_pct = 0.0
            clone_init = state.get("initial_balance", 1000)
            if clone_init > 0:
                clone_bal = state["balance"] + state.get("unrealized_pnl", 0)
                clone_pnl_pct = ((clone_bal - clone_init) / clone_init) * 100

            delta = clone_pnl_pct - brain_pnl_pct
            if delta >= self.ALPHA_THRESHOLD:
                last_delta = self._last_pnl.get(f"alpha_{cid}", 0)
                # Solo emitir si empeoró o es primera vez
                if delta > last_delta + 0.5:
                    self.emit("ALPHA", cid, {
                        "clone_name": clone.name,
                        "clone_pnl_pct": round(clone_pnl_pct, 2),
                        "brain_pnl_pct": round(brain_pnl_pct, 2),
                        "delta": round(delta, 2),
                        "params": clone.params.copy(),
                    })
                    log.info(
                        f"🧠 [SIGNAL:ALPHA] {clone.name} supera al cerebro por "
                        f"+{delta:.1f}% — considerar adoptar parámetros"
                    )
                self._last_pnl[f"alpha_{cid}"] = delta

        # Limpiar discoveries viejas (cada 10 min)
        if len(self._processed_discoveries) > 500:
            self._processed_discoveries = set(list(self._processed_discoveries)[-200:])

    def process_clone_exit(self, clone_name: str, trade: dict, reason: str, pnl_pct: float):
        """Llamar cuando un clon cierra una posición."""
        self.emit("EXIT_WARN", clone_name, {
            "symbol": trade.get("symbol", "?"),
            "mint": trade.get("mint"),
            "reason": reason,
            "pnl_pct": round(pnl_pct, 2),
            "clone_name": clone_name,
        })
        if pnl_pct <= -5:
            log.warning(
                f"⚠️ [SIGNAL:EXIT_WARN] {clone_name} cerró "
                f"{trade.get('symbol', '?')} con {pnl_pct:+.1f}% — posible riesgo para cerebro"
            )

    def get_consensus(self, mint: str) -> dict:
        """Retorna el consenso de clones sobre un token específico."""
        clones_in = self._clone_entries.get(mint, set())
        return {
            "mint": mint,
            "clone_count": len(clones_in),
            "clones": list(clones_in),
            "conviction": len(clones_in) >= 2,
        }

    def get_stats(self) -> dict:
        """Estadísticas del bus de señales para el dashboard."""
        by_type = defaultdict(int)
        for s in self._history:
            by_type[s["type"]] += 1
        return {
            "pending": len(self._signals),
            "total_history": len(self._history),
            "by_type": dict(by_type),
            "tracked_mints": len(self._clone_entries),
            "discoveries": by_type.get("DISCOVERY", 0),
            "hot_trades": by_type.get("HOT_TRADE", 0),
            "convictions": by_type.get("CONVICTION", 0),
            "alphas": by_type.get("ALPHA", 0),
        }


# Singleton global
signal_bus = CloneSignalBus()

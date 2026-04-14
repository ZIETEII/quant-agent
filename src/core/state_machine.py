"""
╔══════════════════════════════════════════════════════════╗
║   STATE MACHINE — Finite State Machine del Bot V3.0      ║
║   Estados: READY, IN_TRADE, COOLDOWN, PROFIT_CAP,       ║
║            LOSS_CAP, ERROR                               ║
╚══════════════════════════════════════════════════════════╝

Transiciones:
  [*] → READY
  READY → IN_TRADE (señal válida + risk approved)
  IN_TRADE → COOLDOWN (trade cerrado)
  COOLDOWN → READY (cooldown terminado)
  READY → PROFIT_CAP (daily profit >= $600)
  READY → LOSS_CAP (daily loss >= $300)
  IN_TRADE → LOSS_CAP (daily loss >= $300)
  PROFIT_CAP → READY (nuevo día 00:00 UTC)
  LOSS_CAP → READY (nuevo día 00:00 UTC)
  READY → ERROR (API/conexión falla)
  IN_TRADE → ERROR (ejecución falla)
  ERROR → READY (recovery exitoso)
"""

import time
import logging
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Callable

log = logging.getLogger("QuantV3.FSM")


class BotState(Enum):
    READY = "READY"
    IN_TRADE = "IN_TRADE"
    COOLDOWN = "COOLDOWN"
    PROFIT_CAP = "PROFIT_CAP"
    LOSS_CAP = "LOSS_CAP"
    ERROR = "ERROR"


@dataclass
class StateTransition:
    """Registro de una transición de estado."""
    from_state: BotState
    to_state: BotState
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))


# Transiciones válidas (from → [to, ...])
VALID_TRANSITIONS = {
    BotState.READY: [BotState.IN_TRADE, BotState.PROFIT_CAP, BotState.LOSS_CAP, BotState.ERROR],
    BotState.IN_TRADE: [BotState.COOLDOWN, BotState.LOSS_CAP, BotState.ERROR],
    BotState.COOLDOWN: [BotState.READY, BotState.PROFIT_CAP, BotState.LOSS_CAP, BotState.ERROR],
    BotState.PROFIT_CAP: [BotState.READY],  # Solo al nuevo día
    BotState.LOSS_CAP: [BotState.READY],     # Solo al nuevo día
    BotState.ERROR: [BotState.READY],         # Recovery manual o automático
}


class StateMachine:
    """
    Máquina de estados finitos para el bot de trading.
    Controla el flujo de operaciones y protege contra comportamientos no deseados.
    """

    def __init__(self):
        self._state = BotState.READY
        self._history: List[StateTransition] = []
        self._cooldown_until: float = 0
        self._error_message: str = ""
        self._active_market: Optional[str] = None  # Mercado de la posición activa
        self._listeners: List[Callable] = []
        self._bot_enabled: bool = False  # Kill switch maestro

        log.info(f"[FSM] Inicializado en estado: {self._state.value}")

    # ══════════════════════════════════════════════════════════
    #  🔄 TRANSICIONES
    # ══════════════════════════════════════════════════════════

    @property
    def state(self) -> BotState:
        """Estado actual del bot."""
        # Auto-resolver cooldown expirado
        if self._state == BotState.COOLDOWN and time.time() >= self._cooldown_until:
            self._transition(BotState.READY, "Cooldown expirado")
        return self._state

    def _transition(self, new_state: BotState, reason: str) -> bool:
        """Ejecuta una transición de estado con validación."""
        old_state = self._state

        # Validar que la transición es legal
        valid_targets = VALID_TRANSITIONS.get(old_state, [])
        if new_state not in valid_targets:
            log.warning(
                f"[FSM] Transición ILEGAL: {old_state.value} → {new_state.value} | "
                f"Permitidas: {[s.value for s in valid_targets]}"
            )
            return False

        self._state = new_state

        transition = StateTransition(
            from_state=old_state,
            to_state=new_state,
            reason=reason,
        )
        self._history.append(transition)
        # Mantener historial acotado
        if len(self._history) > 200:
            self._history = self._history[-150:]

        log.info(f"[FSM] {old_state.value} → {new_state.value} | {reason}")

        # Notificar listeners
        for listener in self._listeners:
            try:
                listener(transition)
            except Exception as e:
                log.warning(f"[FSM] Listener error: {e}")

        return True

    # ── Acciones de transición públicas ──

    def enter_trade(self, market: str) -> bool:
        """Transicionar a IN_TRADE cuando se abre una posición."""
        if not self._bot_enabled:
            log.warning("[FSM] Bot desactivado. No se puede entrar en trade.")
            return False
        self._active_market = market
        return self._transition(BotState.IN_TRADE, f"Posición abierta en {market}")

    def exit_trade(self, cooldown_seconds: int, reason: str = "Trade cerrado") -> bool:
        """Transicionar a COOLDOWN cuando se cierra un trade."""
        self._active_market = None
        self._cooldown_until = time.time() + cooldown_seconds
        return self._transition(BotState.COOLDOWN, f"{reason} | Cooldown: {cooldown_seconds}s")

    def hit_profit_cap(self, pnl: float) -> bool:
        """Transicionar a PROFIT_CAP cuando se alcanza la meta diaria."""
        return self._transition(BotState.PROFIT_CAP, f"Meta diaria alcanzada: +${pnl:.2f}")

    def hit_loss_cap(self, pnl: float) -> bool:
        """Transicionar a LOSS_CAP cuando se alcanza el límite de pérdida."""
        return self._transition(BotState.LOSS_CAP, f"Límite de pérdida diario: ${pnl:.2f}")

    def enter_error(self, error_msg: str) -> bool:
        """Transicionar a ERROR si algo falla."""
        self._error_message = error_msg
        return self._transition(BotState.ERROR, f"Error: {error_msg}")

    def recover(self) -> bool:
        """Recuperar de un estado ERROR o CAP (nuevo día)."""
        if self._state in (BotState.ERROR, BotState.PROFIT_CAP, BotState.LOSS_CAP):
            self._error_message = ""
            return self._transition(BotState.READY, "Recovery / Nuevo día")
        return False

    def daily_reset(self) -> bool:
        """Reset para nuevo día (solo desde PROFIT_CAP o LOSS_CAP)."""
        if self._state in (BotState.PROFIT_CAP, BotState.LOSS_CAP):
            self._error_message = ""
            self._cooldown_until = 0
            return self._transition(BotState.READY, "Nuevo día - Reset de sesión")
        return False

    # ══════════════════════════════════════════════════════════
    #  🎮 CONTROL
    # ══════════════════════════════════════════════════════════

    def enable(self):
        """Enciende el bot."""
        self._bot_enabled = True
        log.info("[FSM] 🟢 Bot HABILITADO")

    def disable(self):
        """Apaga el bot."""
        self._bot_enabled = False
        log.info("[FSM] 🔴 Bot DESHABILITADO")

    @property
    def is_enabled(self) -> bool:
        return self._bot_enabled

    def can_trade(self) -> bool:
        """¿El bot puede abrir un nuevo trade ahora?"""
        return (
            self._bot_enabled
            and self.state == BotState.READY
        )

    def is_in_trade(self) -> bool:
        """¿Hay un trade activo?"""
        return self._state == BotState.IN_TRADE

    def is_stopped(self) -> bool:
        """¿El bot está detenido por caps o error?"""
        return self._state in (BotState.PROFIT_CAP, BotState.LOSS_CAP, BotState.ERROR)

    # ══════════════════════════════════════════════════════════
    #  📊 ESTADO PARA DASHBOARD
    # ══════════════════════════════════════════════════════════

    def get_state_info(self) -> dict:
        """Retorna info completa del estado para el dashboard."""
        current = self.state  # Triggers auto-resolution
        return {
            "state": current.value,
            "bot_enabled": self._bot_enabled,
            "can_trade": self.can_trade(),
            "is_in_trade": self.is_in_trade(),
            "is_stopped": self.is_stopped(),
            "active_market": self._active_market,
            "error_message": self._error_message if current == BotState.ERROR else None,
            "cooldown_remaining": max(0, int(self._cooldown_until - time.time())) if current == BotState.COOLDOWN else 0,
            "history": [
                {
                    "from": t.from_state.value,
                    "to": t.to_state.value,
                    "reason": t.reason,
                    "time": t.timestamp,
                }
                for t in self._history[-20:]  # Últimas 20 transiciones
            ],
        }

    def add_listener(self, callback: Callable):
        """Agrega un listener para transiciones de estado."""
        self._listeners.append(callback)

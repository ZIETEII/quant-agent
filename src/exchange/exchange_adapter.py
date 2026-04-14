"""
╔══════════════════════════════════════════════════════════╗
║   EXCHANGE ADAPTER — Interfaz Abstracta V3.0             ║
║   Permite cambiar Drift por otro exchange en el futuro   ║
║   sin modificar la lógica del bot.                       ║
╚══════════════════════════════════════════════════════════╝
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime


# ══════════════════════════════════════════════════════════
#  📦 DATA MODELS
# ══════════════════════════════════════════════════════════

class PositionDirection(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass
class MarketInfo:
    """Información estática de un mercado."""
    symbol: str              # "SOL-PERP"
    market_index: int        # Drift market index
    base_currency: str       # "SOL"
    min_order_size: float    # Tamaño mínimo de orden
    tick_size: float         # Incremento mínimo de precio
    max_leverage: float      # Apalancamiento máximo permitido


@dataclass
class MarketData:
    """Datos en tiempo real de un mercado."""
    symbol: str
    price: float
    bid: float
    ask: float
    spread: float            # ask - bid
    spread_pct: float        # spread / mid_price * 100
    volume_24h: float
    funding_rate: float      # Rate actual (% por período)
    next_funding_ts: int     # Timestamp del siguiente pago
    open_interest: float
    oracle_price: float      # Precio del oráculo
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class OHLCV:
    """Una vela OHLCV."""
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class OrderRequest:
    """Solicitud para colocar una orden."""
    market_symbol: str
    direction: PositionDirection
    order_type: OrderType
    size: float              # Tamaño en unidades base (ej: 1.5 SOL)
    price: Optional[float] = None  # Solo para LIMIT
    leverage: float = 1.0
    reduce_only: bool = False
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    user_order_id: int = 0


@dataclass
class OrderResult:
    """Resultado de ejecutar una orden."""
    success: bool
    order_id: Optional[str] = None
    tx_hash: Optional[str] = None
    fill_price: float = 0.0
    filled_size: float = 0.0
    fees: float = 0.0
    slippage_pct: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Position:
    """Posición abierta en un mercado."""
    market_symbol: str
    direction: PositionDirection
    size: float              # Tamaño en unidades base
    entry_price: float
    mark_price: float        # Precio actual
    liquidation_price: float
    leverage: float
    unrealized_pnl: float
    realized_pnl: float
    margin_used: float       # Colateral asignado
    funding_accumulated: float
    opened_at: datetime = field(default_factory=datetime.now)


@dataclass
class AccountBalance:
    """Balance de la cuenta de trading."""
    total_collateral: float      # Colateral total depositado
    free_collateral: float       # Disponible para nuevas posiciones
    unrealized_pnl: float        # PnL flotante de posiciones abiertas
    total_position_value: float  # Valor total de posiciones
    margin_ratio: float          # Ratio de margen actual
    leverage_used: float         # Apalancamiento efectivo usado
    available_for_trading: float # Capital operativo
    reserve: float = 0.0        # Reserva intocable


@dataclass
class CloseResult:
    """Resultado de cerrar una posición."""
    success: bool
    realized_pnl: float = 0.0
    fees: float = 0.0
    exit_price: float = 0.0
    tx_hash: Optional[str] = None
    error: Optional[str] = None


# ══════════════════════════════════════════════════════════
#  🔌 INTERFAZ ABSTRACTA
# ══════════════════════════════════════════════════════════

class ExchangeAdapter(ABC):
    """
    Interfaz abstracta para cualquier exchange de perpetuos.
    Implementaciones: DriftClient (Solana), y en el futuro 
    potencialmente Jupiter Perps, Flash Trade, etc.
    """

    @abstractmethod
    async def connect(self) -> bool:
        """Inicializa la conexión al exchange y suscripciones."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Cierra la conexión limpiamente."""
        ...

    @abstractmethod
    async def get_market_data(self, market_symbol: str) -> MarketData:
        """Obtiene datos en tiempo real de un mercado."""
        ...

    @abstractmethod
    async def get_ohlcv(self, market_symbol: str, timeframe: str = "15m", limit: int = 100) -> List[OHLCV]:
        """Obtiene velas históricas para análisis técnico."""
        ...

    @abstractmethod
    async def get_balance(self) -> AccountBalance:
        """Obtiene el balance y estado del colateral."""
        ...

    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """Lista todas las posiciones abiertas."""
        ...

    @abstractmethod
    async def get_position(self, market_symbol: str) -> Optional[Position]:
        """Obtiene una posición específica por mercado."""
        ...

    @abstractmethod
    async def place_order(self, order: OrderRequest) -> OrderResult:
        """Coloca una orden en el exchange."""
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancela una orden pendiente."""
        ...

    @abstractmethod
    async def close_position(self, market_symbol: str, pct: float = 1.0) -> CloseResult:
        """Cierra una posición (total o parcialmente)."""
        ...

    @abstractmethod
    async def get_funding_rate(self, market_symbol: str) -> float:
        """Obtiene el funding rate actual de un mercado."""
        ...

    @abstractmethod
    async def get_market_info(self, market_symbol: str) -> MarketInfo:
        """Obtiene info estática del mercado (leverage max, min order, etc)."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Verifica que la conexión al exchange esté activa."""
        ...

    # ── Utilidades comunes (no abstractas) ──

    def calculate_fees_estimate(self, size: float, price: float) -> float:
        """Estimación de fees para un trade. Override en cada implementación."""
        # Drift taker fee: ~0.1% por defecto
        return size * price * 0.001

    def is_paper_mode(self) -> bool:
        """Retorna True si estamos en modo paper trading."""
        return getattr(self, 'paper_mode', False)

"""
╔══════════════════════════════════════════════════════════╗
║   DRIFT CLIENT — Implementación Drift Protocol V3.0      ║
║   Exchange: Drift Protocol (Solana Perpetuals)           ║
║   SDK: driftpy                                           ║
║   Soporta: Paper Trading (simulación) + Live Trading     ║
╚══════════════════════════════════════════════════════════╝
"""

import os
import time
import math
import logging
import asyncio
import aiohttp
from datetime import datetime
from typing import List, Optional, Dict, Any

from exchange.exchange_adapter import (
    ExchangeAdapter, MarketData, MarketInfo, OHLCV,
    OrderRequest, OrderResult, OrderStatus,
    Position, PositionDirection, OrderType,
    AccountBalance, CloseResult,
)

log = logging.getLogger("QuantV3.Drift")

# ── Market Index Mapping (Drift Protocol v2) ──
DRIFT_MARKETS = {
    "SOL-PERP": {"index": 0, "base": "SOL", "tick": 0.001, "min_size": 0.1, "max_lev": 20},
    "BTC-PERP": {"index": 1, "base": "BTC", "tick": 0.1, "min_size": 0.0001, "max_lev": 20},
    "ETH-PERP": {"index": 2, "base": "ETH", "tick": 0.01, "min_size": 0.001, "max_lev": 20},
}


class DriftExchangeClient(ExchangeAdapter):
    """
    Implementación del ExchangeAdapter para Drift Protocol.
    En PAPER_MODE simula órdenes usando precios reales de oráculos.
    En LIVE_MODE ejecuta órdenes reales via driftpy SDK.
    """

    def __init__(self, paper_mode: bool = True):
        self.paper_mode = paper_mode
        self.wallet_address = os.getenv("SOLANA_WALLET_ADDRESS", "")
        self.rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
        self.drift_env = os.getenv("DRIFT_ENV", "devnet")  # devnet | mainnet
        self.subaccount_id = int(os.getenv("DRIFT_SUBACCOUNT", "0"))

        # SDK objects (initialized on connect)
        self._drift_client = None
        self._drift_user = None
        self._connected = False

        # Paper trading state
        self._paper_balance = float(os.getenv("TRADING_CAPITAL", "5000.0"))
        self._paper_reserve = float(os.getenv("RESERVE_CAPITAL", "2000.0"))
        self._paper_positions: Dict[str, Position] = {}
        self._paper_order_counter = 0
        self._paper_realized_pnl = 0.0

        # Price cache
        self._price_cache: Dict[str, Dict] = {}
        self._price_cache_ttl = 5  # seconds

        # Retry config
        self._max_retries = 3
        self._retry_delay = 1.0  # seconds, with exponential backoff

        log.info(
            f"DriftClient initialized | Mode: {'PAPER' if paper_mode else 'LIVE'} | "
            f"Env: {self.drift_env} | Capital: ${self._paper_balance:.2f}"
        )

    # ══════════════════════════════════════════════════════════
    #  🔌 CONEXIÓN
    # ══════════════════════════════════════════════════════════

    async def connect(self) -> bool:
        """Inicializa la conexión a Drift Protocol."""
        if self.paper_mode:
            log.info("[DRIFT] Paper mode — usando precios de oráculo sin SDK completo")
            self._connected = True
            return True

        try:
            from solders.keypair import Keypair
            from solana.rpc.async_api import AsyncClient
            from driftpy.drift_client import DriftClient
            from driftpy.drift_user import DriftUser
            from driftpy.accounts import get_perp_market_account
            import base58

            # Inicializar conexión Solana
            connection = AsyncClient(self.rpc_url)

            # Cargar keypair
            pk_b58 = os.getenv("SOLANA_PRIVATE_KEY", "")
            if not pk_b58:
                log.error("[DRIFT] SOLANA_PRIVATE_KEY no configurada")
                return False

            keypair = Keypair.from_base58_string(pk_b58)

            # Inicializar DriftClient
            from anchorpy import Wallet, Provider
            wallet = Wallet(keypair)
            provider = Provider(connection, wallet)

            self._drift_client = DriftClient.from_config(
                env=self.drift_env,
                provider=provider,
                authority=keypair.pubkey(),
                active_sub_account_id=self.subaccount_id,
            )

            await self._drift_client.subscribe()

            self._drift_user = DriftUser(
                self._drift_client,
                authority=keypair.pubkey(),
                sub_account_id=self.subaccount_id,
            )
            await self._drift_user.subscribe()

            self._connected = True
            log.info(f"[DRIFT] Conectado exitosamente a {self.drift_env}")
            return True

        except ImportError as e:
            log.error(f"[DRIFT] Dependencias faltantes: {e}. pip install driftpy")
            return False
        except Exception as e:
            log.error(f"[DRIFT] Error de conexión: {e}")
            return False

    async def disconnect(self) -> None:
        """Cierra la conexión a Drift."""
        if self._drift_client:
            try:
                await self._drift_client.unsubscribe()
            except Exception:
                pass
        if self._drift_user:
            try:
                await self._drift_user.unsubscribe()
            except Exception:
                pass
        self._connected = False
        log.info("[DRIFT] Desconectado")

    async def health_check(self) -> bool:
        """Verifica la conexión."""
        if self.paper_mode:
            return True
        return self._connected and self._drift_client is not None

    # ══════════════════════════════════════════════════════════
    #  📊 DATOS DE MERCADO
    # ══════════════════════════════════════════════════════════

    async def get_market_data(self, market_symbol: str) -> MarketData:
        """Obtiene datos en tiempo real del mercado."""
        market = DRIFT_MARKETS.get(market_symbol)
        if not market:
            raise ValueError(f"Mercado no soportado: {market_symbol}")

        price = await self._get_price(market_symbol)
        funding = await self.get_funding_rate(market_symbol)

        # Spread estimation (perpetuos en Drift ~0.02-0.05%)
        spread_pct = 0.03  # Default conservador
        spread = price * spread_pct / 100
        bid = price - spread / 2
        ask = price + spread / 2

        return MarketData(
            symbol=market_symbol,
            price=price,
            bid=bid,
            ask=ask,
            spread=spread,
            spread_pct=spread_pct,
            volume_24h=0,  # Se obtiene de API externa si necesario
            funding_rate=funding,
            next_funding_ts=0,
            open_interest=0,
            oracle_price=price,
        )

    async def get_ohlcv(self, market_symbol: str, timeframe: str = "15m", limit: int = 100) -> List[OHLCV]:
        """Obtiene velas históricas desde GeckoTerminal / DexScreener para el par base."""
        market = DRIFT_MARKETS.get(market_symbol)
        if not market:
            return []

        base = market["base"]
        # Mapeo de tokens a fuentes de datos OHLCV
        coingecko_ids = {"SOL": "solana", "BTC": "bitcoin", "ETH": "ethereum"}
        cg_id = coingecko_ids.get(base)
        if not cg_id:
            return []

        tf_map = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
        minutes = tf_map.get(timeframe, 15)

        try:
            # Usar CoinGecko OHLC como fuente confiable
            days = max(1, (minutes * limit) // 1440 + 1)
            url = f"https://api.coingecko.com/api/v3/coins/{cg_id}/ohlc?vs_currency=usd&days={days}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status != 200:
                        return []
                    data = await r.json()
                    candles = []
                    for item in data[-limit:]:
                        candles.append(OHLCV(
                            timestamp=int(item[0] / 1000),
                            open=float(item[1]),
                            high=float(item[2]),
                            low=float(item[3]),
                            close=float(item[4]),
                            volume=0,
                        ))
                    return candles
        except Exception as e:
            log.warning(f"[DRIFT] Error obteniendo OHLCV para {market_symbol}: {e}")
            return []

    async def _get_price(self, market_symbol: str) -> float:
        """Obtiene el precio actual con cache."""
        cached = self._price_cache.get(market_symbol)
        if cached and (time.time() - cached["ts"]) < self._price_cache_ttl:
            return cached["price"]

        # Live mode: usar oráculo de Drift
        if not self.paper_mode and self._drift_client:
            try:
                market = DRIFT_MARKETS[market_symbol]
                from driftpy.constants.numeric_constants import PRICE_PRECISION
                oracle_data = self._drift_client.get_oracle_price_data_for_perp_market(
                    market["index"]
                )
                price = float(oracle_data.price) / PRICE_PRECISION
                self._price_cache[market_symbol] = {"price": price, "ts": time.time()}
                return price
            except Exception as e:
                log.warning(f"[DRIFT] Oracle price error: {e}")

        # Fallback: CoinGecko API
        return await self._get_price_coingecko(market_symbol)

    async def _get_price_coingecko(self, market_symbol: str) -> float:
        """Precio via CoinGecko (fallback y paper mode)."""
        market = DRIFT_MARKETS.get(market_symbol, {})
        base = market.get("base", "SOL")
        cg_map = {"SOL": "solana", "BTC": "bitcoin", "ETH": "ethereum"}
        cg_id = cg_map.get(base, "solana")

        try:
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 200:
                        data = await r.json()
                        price = float(data.get(cg_id, {}).get("usd", 0))
                        if price > 0:
                            self._price_cache[market_symbol] = {"price": price, "ts": time.time()}
                            return price
        except Exception as e:
            log.warning(f"[DRIFT] CoinGecko price error: {e}")

        # Últimos fallbacks
        fallbacks = {"SOL-PERP": 150.0, "BTC-PERP": 85000.0, "ETH-PERP": 3500.0}
        cached = self._price_cache.get(market_symbol)
        return cached["price"] if cached else fallbacks.get(market_symbol, 0)

    # ══════════════════════════════════════════════════════════
    #  💰 BALANCE Y POSICIONES
    # ══════════════════════════════════════════════════════════

    async def get_balance(self) -> AccountBalance:
        """Obtiene el balance de la cuenta."""
        if self.paper_mode:
            unrealized = sum(p.unrealized_pnl for p in self._paper_positions.values())
            margin_used = sum(p.margin_used for p in self._paper_positions.values())
            total = self._paper_balance + unrealized
            free = self._paper_balance - margin_used
            return AccountBalance(
                total_collateral=self._paper_balance + self._paper_reserve,
                free_collateral=max(0, free),
                unrealized_pnl=unrealized,
                total_position_value=sum(p.size * p.mark_price for p in self._paper_positions.values()),
                margin_ratio=margin_used / total if total > 0 else 0,
                leverage_used=sum(p.size * p.mark_price for p in self._paper_positions.values()) / total if total > 0 else 0,
                available_for_trading=max(0, free),
                reserve=self._paper_reserve,
            )

        # Live mode
        try:
            from driftpy.constants.numeric_constants import QUOTE_PRECISION
            total_col = float(self._drift_user.get_total_collateral()) / QUOTE_PRECISION
            free_col = float(self._drift_user.get_free_collateral()) / QUOTE_PRECISION
            unrealized = float(self._drift_user.get_unrealized_pnl()) / QUOTE_PRECISION

            return AccountBalance(
                total_collateral=total_col,
                free_collateral=free_col,
                unrealized_pnl=unrealized,
                total_position_value=0,
                margin_ratio=0,
                leverage_used=float(self._drift_user.get_leverage()) / 10000,
                available_for_trading=free_col,
                reserve=self._paper_reserve,
            )
        except Exception as e:
            log.error(f"[DRIFT] Balance error: {e}")
            return AccountBalance(
                total_collateral=0, free_collateral=0, unrealized_pnl=0,
                total_position_value=0, margin_ratio=0, leverage_used=0,
                available_for_trading=0,
            )

    async def get_positions(self) -> List[Position]:
        """Lista todas las posiciones abiertas."""
        if self.paper_mode:
            # Actualizar precios de posiciones paper
            for symbol, pos in self._paper_positions.items():
                price = await self._get_price(symbol)
                pos.mark_price = price
                if pos.direction == PositionDirection.LONG:
                    pos.unrealized_pnl = (price - pos.entry_price) * pos.size
                else:
                    pos.unrealized_pnl = (pos.entry_price - price) * pos.size
            return list(self._paper_positions.values())

        # Live mode
        try:
            from driftpy.constants.numeric_constants import BASE_PRECISION, PRICE_PRECISION, QUOTE_PRECISION
            positions = []
            for market_symbol, market_info in DRIFT_MARKETS.items():
                idx = market_info["index"]
                perp_pos = self._drift_user.get_perp_position(idx)
                if perp_pos and perp_pos.base_asset_amount != 0:
                    size = abs(float(perp_pos.base_asset_amount)) / BASE_PRECISION
                    direction = PositionDirection.LONG if perp_pos.base_asset_amount > 0 else PositionDirection.SHORT
                    entry = float(perp_pos.quote_entry_amount) / QUOTE_PRECISION / size if size > 0 else 0
                    price = await self._get_price(market_symbol)
                    if direction == PositionDirection.LONG:
                        unrealized = (price - entry) * size
                    else:
                        unrealized = (entry - price) * size

                    positions.append(Position(
                        market_symbol=market_symbol,
                        direction=direction,
                        size=size,
                        entry_price=entry,
                        mark_price=price,
                        liquidation_price=0,
                        leverage=1.0,
                        unrealized_pnl=unrealized,
                        realized_pnl=0,
                        margin_used=0,
                        funding_accumulated=0,
                    ))
            return positions
        except Exception as e:
            log.error(f"[DRIFT] Positions error: {e}")
            return []

    async def get_position(self, market_symbol: str) -> Optional[Position]:
        """Obtiene una posición específica."""
        positions = await self.get_positions()
        for p in positions:
            if p.market_symbol == market_symbol:
                return p
        return None

    # ══════════════════════════════════════════════════════════
    #  📝 ÓRDENES
    # ══════════════════════════════════════════════════════════

    async def place_order(self, order: OrderRequest) -> OrderResult:
        """Coloca una orden en Drift."""
        market = DRIFT_MARKETS.get(order.market_symbol)
        if not market:
            return OrderResult(success=False, error=f"Mercado no soportado: {order.market_symbol}")

        if self.paper_mode:
            return await self._paper_place_order(order, market)
        else:
            return await self._live_place_order(order, market)

    async def _paper_place_order(self, order: OrderRequest, market: dict) -> OrderResult:
        """Simula una orden usando precios reales."""
        price = await self._get_price(order.market_symbol)
        if price <= 0:
            return OrderResult(success=False, error="No se pudo obtener precio")

        # Calcular fee (~0.1% taker en Drift)
        notional = order.size * price
        fee = notional * 0.001

        # Calcular margen requerido
        margin_required = notional / order.leverage

        # Verificar balance
        if margin_required + fee > self._paper_balance:
            return OrderResult(
                success=False,
                error=f"Balance insuficiente: necesita ${margin_required + fee:.2f}, tiene ${self._paper_balance:.2f}",
            )

        # Simular slippage (0.02-0.05% para majors)
        import random
        slippage_pct = random.uniform(0.01, 0.04) / 100
        if order.direction == PositionDirection.LONG:
            fill_price = price * (1 + slippage_pct)
        else:
            fill_price = price * (1 - slippage_pct)

        # Ejecutar en paper
        self._paper_balance -= (margin_required + fee)
        self._paper_order_counter += 1

        # Calcular precio de liquidación
        if order.direction == PositionDirection.LONG:
            liq_price = fill_price * (1 - 1 / order.leverage * 0.9)  # 90% del margen
        else:
            liq_price = fill_price * (1 + 1 / order.leverage * 0.9)

        # Crear o actualizar posición
        existing = self._paper_positions.get(order.market_symbol)
        if existing and existing.direction == order.direction:
            # Aumentar posición existente
            total_size = existing.size + order.size
            avg_entry = (existing.entry_price * existing.size + fill_price * order.size) / total_size
            existing.size = total_size
            existing.entry_price = avg_entry
            existing.margin_used += margin_required
        else:
            self._paper_positions[order.market_symbol] = Position(
                market_symbol=order.market_symbol,
                direction=order.direction,
                size=order.size,
                entry_price=fill_price,
                mark_price=fill_price,
                liquidation_price=liq_price,
                leverage=order.leverage,
                unrealized_pnl=0,
                realized_pnl=0,
                margin_used=margin_required,
                funding_accumulated=0,
            )

        order_id = f"PAPER-{self._paper_order_counter}"
        log.info(
            f"[PAPER ORDER] {order.direction.value} {order.size:.4f} {order.market_symbol} "
            f"@ ${fill_price:.2f} | Margin: ${margin_required:.2f} | Fee: ${fee:.2f} | "
            f"Lev: {order.leverage}x"
        )

        return OrderResult(
            success=True,
            order_id=order_id,
            tx_hash=f"PAPER_{int(time.time() * 1000)}",
            fill_price=fill_price,
            filled_size=order.size,
            fees=fee,
            slippage_pct=slippage_pct * 100,
            status=OrderStatus.FILLED,
        )

    async def _live_place_order(self, order: OrderRequest, market: dict) -> OrderResult:
        """Ejecuta una orden real en Drift Protocol."""
        for attempt in range(1, self._max_retries + 1):
            try:
                from driftpy.constants.numeric_constants import BASE_PRECISION, PRICE_PRECISION
                from driftpy.types import (
                    OrderParams as DriftOrderParams,
                    OrderType as DriftOrderType,
                    PositionDirection as DriftDirection,
                    MarketType as DriftMarketType,
                )

                # Convertir tipos
                drift_direction = DriftDirection.LONG() if order.direction == PositionDirection.LONG else DriftDirection.SHORT()
                base_amount = int(order.size * BASE_PRECISION)

                if order.order_type == OrderType.MARKET:
                    drift_order_type = DriftOrderType.MARKET()
                    price = 0
                else:
                    drift_order_type = DriftOrderType.LIMIT()
                    price = int(order.price * PRICE_PRECISION) if order.price else 0

                params = DriftOrderParams(
                    order_type=drift_order_type,
                    market_type=DriftMarketType.PERP(),
                    direction=drift_direction,
                    user_order_id=order.user_order_id,
                    base_asset_amount=base_amount,
                    price=price,
                    market_index=market["index"],
                    reduce_only=order.reduce_only,
                )

                tx_sig = await self._drift_client.place_perp_order(params)

                fill_price = await self._get_price(order.market_symbol)
                log.info(f"[LIVE ORDER] {order.direction.value} {order.size:.4f} {order.market_symbol} | TX: {tx_sig}")

                return OrderResult(
                    success=True,
                    order_id=str(tx_sig),
                    tx_hash=str(tx_sig),
                    fill_price=fill_price,
                    filled_size=order.size,
                    fees=order.size * fill_price * 0.001,
                    status=OrderStatus.FILLED,
                )

            except Exception as e:
                log.warning(f"[DRIFT] Order attempt {attempt}/{self._max_retries} failed: {e}")
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_delay * (2 ** (attempt - 1)))
                else:
                    return OrderResult(success=False, error=f"Orden fallida después de {self._max_retries} intentos: {e}")

        return OrderResult(success=False, error="Unreachable")

    async def cancel_order(self, order_id: str) -> bool:
        """Cancela una orden pendiente."""
        if self.paper_mode:
            return True
        try:
            await self._drift_client.cancel_order(int(order_id))
            return True
        except Exception as e:
            log.error(f"[DRIFT] Cancel order error: {e}")
            return False

    async def close_position(self, market_symbol: str, pct: float = 1.0) -> CloseResult:
        """Cierra una posición (total o parcialmente)."""
        if self.paper_mode:
            return await self._paper_close_position(market_symbol, pct)
        else:
            return await self._live_close_position(market_symbol, pct)

    async def _paper_close_position(self, market_symbol: str, pct: float) -> CloseResult:
        """Cierra posición paper."""
        pos = self._paper_positions.get(market_symbol)
        if not pos:
            return CloseResult(success=False, error="No hay posición abierta")

        price = await self._get_price(market_symbol)
        close_size = pos.size * pct

        # Calcular PnL
        if pos.direction == PositionDirection.LONG:
            pnl = (price - pos.entry_price) * close_size
        else:
            pnl = (pos.entry_price - price) * close_size

        fee = close_size * price * 0.001  # 0.1% taker fee
        net_pnl = pnl - fee

        # Devolver margen + PnL al balance
        margin_returned = pos.margin_used * pct
        self._paper_balance += margin_returned + net_pnl
        self._paper_realized_pnl += net_pnl

        if pct >= 1.0:
            del self._paper_positions[market_symbol]
        else:
            pos.size -= close_size
            pos.margin_used -= margin_returned

        log.info(
            f"[PAPER CLOSE] {market_symbol} | Size: {close_size:.4f} | "
            f"Entry: ${pos.entry_price:.2f} → Exit: ${price:.2f} | "
            f"PnL: ${net_pnl:+.2f} | Fee: ${fee:.2f}"
        )

        return CloseResult(
            success=True,
            realized_pnl=net_pnl,
            fees=fee,
            exit_price=price,
            tx_hash=f"PAPER_CLOSE_{int(time.time() * 1000)}",
        )

    async def _live_close_position(self, market_symbol: str, pct: float) -> CloseResult:
        """Cierra posición real en Drift."""
        market = DRIFT_MARKETS.get(market_symbol)
        if not market:
            return CloseResult(success=False, error=f"Mercado no soportado: {market_symbol}")

        try:
            from driftpy.constants.numeric_constants import BASE_PRECISION

            pos = await self.get_position(market_symbol)
            if not pos:
                return CloseResult(success=False, error="No hay posición abierta")

            close_size = int(pos.size * pct * BASE_PRECISION)

            # Orden de cierre = dirección opuesta, reduce_only
            close_direction = PositionDirection.SHORT if pos.direction == PositionDirection.LONG else PositionDirection.LONG

            result = await self.place_order(OrderRequest(
                market_symbol=market_symbol,
                direction=close_direction,
                order_type=OrderType.MARKET,
                size=pos.size * pct,
                leverage=pos.leverage,
                reduce_only=True,
            ))

            exit_price = await self._get_price(market_symbol)
            if pos.direction == PositionDirection.LONG:
                pnl = (exit_price - pos.entry_price) * pos.size * pct
            else:
                pnl = (pos.entry_price - exit_price) * pos.size * pct

            return CloseResult(
                success=result.success,
                realized_pnl=pnl - result.fees,
                fees=result.fees,
                exit_price=exit_price,
                tx_hash=result.tx_hash,
                error=result.error,
            )

        except Exception as e:
            log.error(f"[DRIFT] Close position error: {e}")
            return CloseResult(success=False, error=str(e))

    # ══════════════════════════════════════════════════════════
    #  📈 FUNDING RATE
    # ══════════════════════════════════════════════════════════

    async def get_funding_rate(self, market_symbol: str) -> float:
        """Obtiene el funding rate actual."""
        if self.paper_mode or not self._drift_client:
            # Estimar desde Binance como proxy (igual que V2.0)
            binance_map = {"SOL-PERP": "SOLUSDT", "BTC-PERP": "BTCUSDT", "ETH-PERP": "ETHUSDT"}
            binance_sym = binance_map.get(market_symbol)
            if binance_sym:
                try:
                    url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={binance_sym}"
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                            if r.status == 200:
                                data = await r.json()
                                return float(data.get("lastFundingRate", 0)) * 100
                except Exception:
                    pass
            return 0.0

        try:
            market = DRIFT_MARKETS[market_symbol]
            from driftpy.constants.numeric_constants import FUNDING_RATE_PRECISION
            perp_market = self._drift_client.get_perp_market_account(market["index"])
            rate = float(perp_market.amm.last_funding_rate) / FUNDING_RATE_PRECISION * 100
            return rate
        except Exception as e:
            log.warning(f"[DRIFT] Funding rate error: {e}")
            return 0.0

    async def get_market_info(self, market_symbol: str) -> MarketInfo:
        """Obtiene info estática del mercado."""
        market = DRIFT_MARKETS.get(market_symbol)
        if not market:
            raise ValueError(f"Mercado no soportado: {market_symbol}")

        return MarketInfo(
            symbol=market_symbol,
            market_index=market["index"],
            base_currency=market["base"],
            min_order_size=market["min_size"],
            tick_size=market["tick"],
            max_leverage=market["max_lev"],
        )

    # ══════════════════════════════════════════════════════════
    #  🔧 UTILIDADES
    # ══════════════════════════════════════════════════════════

    def get_paper_state(self) -> dict:
        """Retorna el estado completo del paper trading para debug/dashboard."""
        return {
            "balance": self._paper_balance,
            "reserve": self._paper_reserve,
            "realized_pnl": self._paper_realized_pnl,
            "positions": {
                k: {
                    "direction": v.direction.value,
                    "size": v.size,
                    "entry_price": v.entry_price,
                    "mark_price": v.mark_price,
                    "unrealized_pnl": v.unrealized_pnl,
                    "margin_used": v.margin_used,
                    "leverage": v.leverage,
                }
                for k, v in self._paper_positions.items()
            },
            "total_equity": self._paper_balance + sum(p.unrealized_pnl for p in self._paper_positions.values()),
        }

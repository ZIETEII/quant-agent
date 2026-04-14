"""
╔══════════════════════════════════════════════════════════╗
║   QUANT AGENT V3.0 — "THE DISCIPLINE ENGINE"             ║
║   Backend Web FastAPI + Motor de Trading Institucional    ║
║   Exchange: Drift Protocol (Solana Perpetuals)           ║
║   Mercados: SOL-PERP, BTC-PERP, ETH-PERP                ║
║   Filosofía: Operar solo setups válidos. Sobrevivir.     ║
╚══════════════════════════════════════════════════════════╝
"""

import os
import time
import asyncio
import logging
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import uvicorn
import aiohttp

# ── V3.0 Modules ──
from exchange.drift_client import DriftExchangeClient
from core.risk_engine import RiskEngine
from core.position_sizer import calculate_position_size
from core.state_machine import StateMachine, BotState
from core.signal_engine import SignalEngine, StrategyType
from ai.regime_detector import RegimeDetector, MarketRegime
from ai.sentiment import update_sentiment, get_risk_modifier, get_sentiment_summary

# ══════════════════════════════════════════════════════════
#  ⚙️  CONFIGURACIÓN INICIAL
# ══════════════════════════════════════════════════════════
load_dotenv()

PAPER_TRADING_MODE = os.getenv("PAPER_TRADING_MODE", "True").lower() in ['true', '1', 'yes']
MARKETS = os.getenv("MARKETS", "SOL-PERP,BTC-PERP,ETH-PERP").split(",")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_SECONDS", "30"))  # 30s (no 5s como V2.0)

# ── Telegram ──
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("QuantV3")

# ── Telegram Notifier ──
async def notify_telegram(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        async with aiohttp.ClientSession() as s:
            await s.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5))
    except Exception as e:
        log.warning(f"Telegram error: {e}")

# ── Inicializar módulos V3.0 ──
exchange = DriftExchangeClient(paper_mode=PAPER_TRADING_MODE)
risk_engine = RiskEngine()
state_machine = StateMachine()
signal_engine = SignalEngine()
regime_detector = RegimeDetector()

# ══════════════════════════════════════════════════════════
#  📊 APP STATE (para Dashboard)
# ══════════════════════════════════════════════════════════

app_state = {
    "version": "3.0",
    "mode": "Paper" if PAPER_TRADING_MODE else "Live",
    "markets": MARKETS,

    # Estado del bot
    "bot_state": "READY",
    "bot_enabled": False,
    "state_info": {},

    # Métricas de sesión
    "session": {},
    "balance": {},

    # Market Data
    "market_data": {},       # {market_symbol: MarketData}
    "regime_analysis": {},   # {market_symbol: RegimeAnalysis}

    # Posición activa
    "active_position": None,
    "position_history": [],  # Últimos N trades del día

    # Señales
    "last_signals": {},      # {market_symbol: TradeSignal info}
    "decisions_log": [],     # Log de decisiones (incluyendo NO_TRADE)

    # Sentiment
    "sentiment": {},

    # Logs
    "logs": [],
    "scan_interval": SCAN_INTERVAL,
    "last_scan": None,
}


def add_log(msg, log_type="info"):
    now = datetime.now().strftime("%H:%M:%S")
    log_id = len(app_state["logs"])
    app_state["logs"].append({"id": log_id, "time": now, "type": log_type, "msg": msg})
    if len(app_state["logs"]) > 200:
        app_state["logs"] = app_state["logs"][-150:]


def add_decision(msg, decision_type="info"):
    """Registra una decisión del bot (incluyendo NO TRADE como decisión activa)."""
    now = datetime.now().strftime("%H:%M:%S")
    app_state["decisions_log"].insert(0, {"time": now, "type": decision_type, "msg": msg})
    if len(app_state["decisions_log"]) > 100:
        app_state["decisions_log"] = app_state["decisions_log"][:100]


# ══════════════════════════════════════════════════════════
#  🧠 ENGINE LOOP V3.0 — La Disciplina
# ══════════════════════════════════════════════════════════

async def engine_loop():
    """
    Loop principal del Quant Agent V3.0.
    Simplificado, modular, disciplinado.
    """
    # Conectar al exchange
    connected = await exchange.connect()
    if not connected:
        add_log("❌ No se pudo conectar al exchange. Verificar configuración.", "error")
        state_machine.enter_error("Conexión al exchange fallida")
        return

    add_log(f"🚀 Quant Agent V3.0 iniciado | Modo: {app_state['mode']} | Mercados: {', '.join(MARKETS)}", "info")
    add_log(f"💰 Capital: ${risk_engine.trading_capital:,.0f} | Reserva: ${risk_engine.reserve_capital:,.0f}", "info")
    add_log(f"🛡️ Profit Cap: +${risk_engine.daily_profit_cap:,.0f} | Loss Cap: -${risk_engine.daily_loss_cap:,.0f}", "info")
    add_log(f"📊 Riesgo/Trade: {risk_engine.risk_per_trade_pct*100:.2f}% = ${risk_engine.trading_capital * risk_engine.risk_per_trade_pct:.0f}", "info")

    await notify_telegram(
        f"🧠 <b>Quant Agent V3.0 — The Discipline Engine</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Capital: <code>${risk_engine.trading_capital:,.0f}</code>\n"
        f"🛡️ Profit Cap: <code>+${risk_engine.daily_profit_cap:,.0f}</code>\n"
        f"🔴 Loss Cap: <code>-${risk_engine.daily_loss_cap:,.0f}</code>\n"
        f"📊 Riesgo/Trade: <code>${risk_engine.trading_capital * risk_engine.risk_per_trade_pct:.0f}</code>\n"
        f"🎮 Modo: {app_state['mode']}\n"
        f"📈 Mercados: {', '.join(MARKETS)}"
    )

    while True:
        try:
            # ── 1. ¿Bot habilitado? ──
            if not state_machine.is_enabled:
                app_state["bot_state"] = "DISABLED"
                app_state["state_info"] = state_machine.get_state_info()
                await asyncio.sleep(5)
                continue

            # ── 2. Obtener estado actual ──
            current_state = state_machine.state  # Auto-resuelve cooldowns
            app_state["bot_state"] = current_state.value
            app_state["state_info"] = state_machine.get_state_info()
            app_state["session"] = risk_engine.get_session_state()
            app_state["last_scan"] = datetime.now().strftime("%H:%M:%S")

            # ── 3. ¿Estado permite operar? ──
            if current_state in (BotState.PROFIT_CAP, BotState.LOSS_CAP, BotState.ERROR):
                add_log(f"⏸ Bot en estado {current_state.value}. Esperando.", "info")
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            if current_state == BotState.COOLDOWN:
                remaining = state_machine.get_state_info()["cooldown_remaining"]
                add_log(f"⏱ Cooldown: {remaining}s restantes", "info")
                await asyncio.sleep(min(10, remaining + 1))
                continue

            # ── 4. ¿Ya hay posición abierta? Monitorear. ──
            if current_state == BotState.IN_TRADE:
                await _monitor_active_position()
                await asyncio.sleep(5)  # Monitoreo cada 5s cuando hay posición
                continue

            # ── 5. ESTADO READY: Buscar señales ──
            assert current_state == BotState.READY

            # Health check
            healthy = await exchange.health_check()
            kill_reason = risk_engine.should_emergency_stop(api_healthy=healthy)
            if kill_reason:
                state_machine.enter_error(kill_reason)
                add_log(f"🚨 {kill_reason}", "error")
                await notify_telegram(f"🚨 <b>EMERGENCY STOP</b>\n{kill_reason}")
                continue

            # ── 6. Actualizar datos de mercado ──
            balance = await exchange.get_balance()
            app_state["balance"] = {
                "total_collateral": balance.total_collateral,
                "free_collateral": balance.free_collateral,
                "unrealized_pnl": balance.unrealized_pnl,
                "available": balance.available_for_trading,
                "reserve": balance.reserve,
                "equity": balance.total_collateral + balance.unrealized_pnl,
            }

            best_signal = None
            best_confidence = 0

            for market in MARKETS:
                try:
                    # Obtener velas y datos de mercado
                    candles = await exchange.get_ohlcv(market, timeframe="15m", limit=100)
                    market_data = await exchange.get_market_data(market)
                    app_state["market_data"][market] = {
                        "price": market_data.price,
                        "spread_pct": market_data.spread_pct,
                        "funding_rate": market_data.funding_rate,
                    }

                    if len(candles) < 55:
                        add_decision(f"📊 {market}: Datos insuficientes ({len(candles)} velas)", "info")
                        continue

                    # ── 7. Detectar régimen ──
                    regime = await regime_detector.detect(candles, market)
                    app_state["regime_analysis"][market] = {
                        "regime": regime.regime.value,
                        "confidence": regime.confidence,
                        "adx": regime.adx,
                        "rsi": regime.rsi,
                        "trend": regime.trend_direction,
                        "recommendation": regime.recommendation,
                    }

                    # ── 8. Buscar señal ──
                    signal = await signal_engine.scan(market, candles, regime)

                    if signal and signal.valid:
                        app_state["last_signals"][market] = {
                            "strategy": signal.strategy.value,
                            "direction": signal.direction.value,
                            "entry": signal.entry_price,
                            "sl": signal.stop_loss,
                            "tp": signal.take_profit,
                            "rr": signal.risk_reward,
                            "confidence": signal.confidence,
                            "reason": signal.reason,
                            "indicators": signal.indicators,
                        }
                        add_decision(f"✅ {market}: {signal.reason}", "signal")

                        if signal.confidence > best_confidence:
                            best_signal = signal
                            best_confidence = signal.confidence
                    elif signal and not signal.valid:
                        # NO_TRADE es una decisión activa
                        add_decision(f"⏸ {market}: {signal.reason}", "no_trade")
                        app_state["last_signals"][market] = {
                            "strategy": "NO_TRADE",
                            "reason": signal.reason,
                        }
                    else:
                        add_decision(f"🔍 {market}: Sin señal en {regime.regime.value}", "scan")

                except Exception as e:
                    log.error(f"[ENGINE] Error escaneando {market}: {e}")
                    add_log(f"⚠️ Error en {market}: {e}", "warn")

            # ── 9. Si hay señal, validate con Risk Engine ──
            if best_signal:
                positions = await exchange.get_positions()
                risk_decision = risk_engine.validate_entry(
                    entry_price=best_signal.entry_price,
                    stop_loss_price=best_signal.stop_loss,
                    take_profit_price=best_signal.take_profit,
                    direction=best_signal.direction.value,
                    current_positions=len(positions),
                    funding_rate=app_state["market_data"].get(best_signal.market_symbol, {}).get("funding_rate", 0),
                    spread_pct=app_state["market_data"].get(best_signal.market_symbol, {}).get("spread_pct", 0),
                )

                if risk_decision.approved:
                    add_decision(f"✅ RISK APPROVED: {risk_decision.reason}", "approved")

                    # ── 10. Calcular tamaño de posición ──
                    market_info = await exchange.get_market_info(best_signal.market_symbol)
                    size_result = calculate_position_size(
                        capital=risk_engine.trading_capital,
                        risk_per_trade_pct=risk_engine.risk_per_trade_pct,
                        entry_price=best_signal.entry_price,
                        stop_loss_price=best_signal.stop_loss,
                        take_profit_price=best_signal.take_profit,
                        direction=best_signal.direction.value,
                        max_leverage=3.0,
                        min_order_size=market_info.min_order_size,
                    )

                    if size_result.valid:
                        # ── 11. EJECUTAR ORDEN ──
                        from exchange.exchange_adapter import OrderRequest, OrderType
                        order_result = await exchange.place_order(OrderRequest(
                            market_symbol=best_signal.market_symbol,
                            direction=best_signal.direction,
                            order_type=OrderType.MARKET,
                            size=size_result.position_size,
                            leverage=size_result.leverage_used,
                        ))

                        if order_result.success:
                            # ── 12. Transición de estado ──
                            state_machine.enter_trade(best_signal.market_symbol)

                            app_state["active_position"] = {
                                "market": best_signal.market_symbol,
                                "direction": best_signal.direction.value,
                                "strategy": best_signal.strategy.value,
                                "entry_price": order_result.fill_price,
                                "size": order_result.filled_size,
                                "stop_loss": best_signal.stop_loss,
                                "take_profit": best_signal.take_profit,
                                "risk_amount": size_result.risk_amount,
                                "rr_ratio": size_result.risk_reward_ratio,
                                "fees": order_result.fees,
                                "opened_at": datetime.now().isoformat(),
                                "tx_hash": order_result.tx_hash,
                            }

                            add_log(
                                f"🎯 TRADE ABIERTO: {best_signal.direction.value} "
                                f"{size_result.position_size:.4f} {best_signal.market_symbol} "
                                f"@ ${order_result.fill_price:.2f} | "
                                f"SL: ${best_signal.stop_loss:.2f} | TP: ${best_signal.take_profit:.2f} | "
                                f"R:R: {size_result.risk_reward_ratio:.2f} | "
                                f"Risk: ${size_result.risk_amount:.2f}",
                                "info"
                            )
                            add_decision(
                                f"🎯 EJECUTADO: {best_signal.direction.value} {best_signal.market_symbol} "
                                f"({best_signal.strategy.value}) | R:R {size_result.risk_reward_ratio:.2f}",
                                "executed"
                            )

                            await notify_telegram(
                                f"🎯 <b>TRADE ABIERTO — V3.0</b>\n"
                                f"━━━━━━━━━━━━━━━━━━\n"
                                f"📊 {best_signal.direction.value} <b>{best_signal.market_symbol}</b>\n"
                                f"📐 Estrategia: {best_signal.strategy.value}\n"
                                f"💰 Entry: <code>${order_result.fill_price:.2f}</code>\n"
                                f"🛑 SL: <code>${best_signal.stop_loss:.2f}</code>\n"
                                f"🎯 TP: <code>${best_signal.take_profit:.2f}</code>\n"
                                f"📏 R:R: <code>{size_result.risk_reward_ratio:.2f}</code>\n"
                                f"💼 Size: <code>{size_result.position_size:.4f}</code>\n"
                                f"⚠️ Risk: <code>${size_result.risk_amount:.2f}</code>"
                            )
                        else:
                            add_log(f"❌ Orden fallida: {order_result.error}", "error")
                            add_decision(f"❌ EJECUCIÓN FALLIDA: {order_result.error}", "error")
                    else:
                        add_decision(f"❌ SIZE INVÁLIDO: {size_result.reason}", "rejected")
                else:
                    add_decision(f"🛡️ RISK REJECTED: {risk_decision.reason}", "rejected")

            await asyncio.sleep(SCAN_INTERVAL)

        except Exception as e:
            import traceback
            log.error(f"Engine loop error: {e}")
            log.error(traceback.format_exc())
            add_log(f"⚠️ Error en engine: {e}", "error")
            await asyncio.sleep(10)


# ══════════════════════════════════════════════════════════
#  📡 MONITOR DE POSICIÓN ACTIVA
# ══════════════════════════════════════════════════════════

async def _monitor_active_position():
    """Monitorea la posición activa y ejecuta SL/TP."""
    pos_info = app_state.get("active_position")
    if not pos_info:
        # Sin posición pero en estado IN_TRADE → recovery
        state_machine.exit_trade(60, "Posición no encontrada (recovery)")
        return

    market = pos_info["market"]
    try:
        positions = await exchange.get_positions()
        pos = next((p for p in positions if p.market_symbol == market), None)

        if not pos:
            # Posición fue cerrada externamente
            state_machine.exit_trade(risk_engine.cooldown_after_win, "Posición cerrada externamente")
            app_state["active_position"] = None
            return

        # Actualizar datos en tiempo real
        direction = pos_info["direction"]
        entry = pos_info["entry_price"]
        current = pos.mark_price
        sl = pos_info["stop_loss"]
        tp = pos_info["take_profit"]

        if direction == "LONG":
            pnl_pct = ((current - entry) / entry) * 100
            pnl_usd = (current - entry) * pos.size
            hit_sl = current <= sl
            hit_tp = current >= tp
        else:
            pnl_pct = ((entry - current) / entry) * 100
            pnl_usd = (entry - current) * pos.size
            hit_sl = current >= sl
            hit_tp = current <= tp

        pos_info["current_price"] = current
        pos_info["pnl_pct"] = round(pnl_pct, 2)
        pos_info["pnl_usd"] = round(pnl_usd, 2)

        # ── CHECK STOP LOSS ──
        if hit_sl:
            close_result = await exchange.close_position(market)
            if close_result.success:
                is_win = close_result.realized_pnl > 0
                risk_engine.record_trade_result(close_result.realized_pnl, is_win)
                cooldown = risk_engine.cooldown_after_loss
                state_machine.exit_trade(cooldown, f"STOP LOSS hit: ${close_result.realized_pnl:+.2f}")

                _log_trade_close("STOP_LOSS", pos_info, close_result)

                # Check caps
                session = risk_engine.get_session_state()
                if session["profit_cap_reached"]:
                    state_machine.hit_profit_cap(session["realized_pnl"])
                elif session["loss_cap_reached"]:
                    state_machine.hit_loss_cap(session["realized_pnl"])

                app_state["active_position"] = None

        # ── CHECK TAKE PROFIT ──
        elif hit_tp:
            close_result = await exchange.close_position(market)
            if close_result.success:
                is_win = close_result.realized_pnl > 0
                risk_engine.record_trade_result(close_result.realized_pnl, is_win)
                cooldown = risk_engine.cooldown_after_win
                state_machine.exit_trade(cooldown, f"TAKE PROFIT hit: ${close_result.realized_pnl:+.2f}")

                _log_trade_close("TAKE_PROFIT", pos_info, close_result)

                session = risk_engine.get_session_state()
                if session["profit_cap_reached"]:
                    state_machine.hit_profit_cap(session["realized_pnl"])

                app_state["active_position"] = None

        # ── CHECK LIQUIDATION RISK ──
        elif pos.liquidation_price > 0:
            if direction == "LONG" and current < pos.liquidation_price * 1.1:
                add_log(f"⚠️ ALERTA: Precio cerca de liquidación (${pos.liquidation_price:.2f})", "error")
            elif direction == "SHORT" and current > pos.liquidation_price * 0.9:
                add_log(f"⚠️ ALERTA: Precio cerca de liquidación (${pos.liquidation_price:.2f})", "error")

    except Exception as e:
        log.error(f"[MONITOR] Error: {e}")
        add_log(f"⚠️ Error monitoreando posición: {e}", "error")


def _log_trade_close(reason: str, pos_info: dict, close_result):
    """Loguea el cierre de un trade."""
    emoji = "✅" if close_result.realized_pnl > 0 else "❌"
    add_log(
        f"{emoji} {reason}: {pos_info['market']} | "
        f"PnL: ${close_result.realized_pnl:+.2f} | "
        f"Entry: ${pos_info['entry_price']:.2f} → Exit: ${close_result.exit_price:.2f}",
        "info" if close_result.realized_pnl > 0 else "warn"
    )
    add_decision(
        f"{emoji} CERRADO ({reason}): {pos_info['market']} | PnL: ${close_result.realized_pnl:+.2f}",
        "close"
    )
    app_state["position_history"].insert(0, {
        "market": pos_info["market"],
        "direction": pos_info["direction"],
        "strategy": pos_info["strategy"],
        "entry": pos_info["entry_price"],
        "exit": close_result.exit_price,
        "pnl": close_result.realized_pnl,
        "reason": reason,
        "time": datetime.now().strftime("%H:%M:%S"),
    })
    if len(app_state["position_history"]) > 50:
        app_state["position_history"] = app_state["position_history"][:50]

    asyncio.create_task(notify_telegram(
        f"{emoji} <b>TRADE CERRADO — {reason}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 {pos_info['direction']} {pos_info['market']}\n"
        f"💰 PnL: <b>${close_result.realized_pnl:+.2f}</b>\n"
        f"➡️ Entry: <code>${pos_info['entry_price']:.2f}</code>\n"
        f"⬅️ Exit: <code>${close_result.exit_price:.2f}</code>"
    ))


# ══════════════════════════════════════════════════════════
#  🌐 FASTAPI APP
# ══════════════════════════════════════════════════════════

async def sentiment_polling_loop():
    """Actualiza sentimiento del mercado cada 10 minutos."""
    while True:
        try:
            result = await update_sentiment()
            app_state["sentiment"] = get_sentiment_summary()
            add_log(
                f"🧠 Sentiment: F&G={result['fear_greed_value']} ({result['sentiment_signal']}) | "
                f"Heat={result['market_heat']} | Risk={result['risk_modifier']:.2f}x",
                "info"
            )
        except Exception as e:
            log.warning(f"Sentiment polling error: {e}")
        await asyncio.sleep(600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    asyncio.create_task(engine_loop())
    asyncio.create_task(sentiment_polling_loop())
    add_log("🧠 Quant Agent V3.0 — Motor arrancado", "info")
    yield
    # Shutdown
    await exchange.disconnect()
    add_log("🔌 Desconectado", "info")


app = FastAPI(title="Quant Agent V3.0", lifespan=lifespan)
security = HTTPBasic()
templates = Jinja2Templates(directory="web/templates")
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# Rate Limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Auth ──
WEB_USER = os.getenv("WEB_USER", "admin")
WEB_PASS = os.getenv("WEB_PASS", "quant123")


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_user = secrets.compare_digest(credentials.username, WEB_USER)
    correct_pass = secrets.compare_digest(credentials.password, WEB_PASS)
    if not (correct_user and correct_pass):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return credentials.username


# ══════════════════════════════════════════════════════════
#  📄 ROUTES
# ══════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, user: str = Depends(verify_credentials)):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/state")
async def api_state(user: str = Depends(verify_credentials)):
    """Endpoint principal: todo el estado del bot para el dashboard."""
    return JSONResponse(app_state)


@app.post("/api/toggle")
async def api_toggle(user: str = Depends(verify_credentials)):
    """Encender/Apagar el bot."""
    if state_machine.is_enabled:
        state_machine.disable()
        add_log("🔴 Bot DESACTIVADO por el usuario", "warn")
    else:
        state_machine.enable()
        add_log("🟢 Bot ACTIVADO por el usuario", "info")
    return {"enabled": state_machine.is_enabled}


@app.post("/api/emergency-close")
async def api_emergency_close(user: str = Depends(verify_credentials)):
    """Cierra toda posición abierta de emergencia."""
    closed = []
    for market in MARKETS:
        result = await exchange.close_position(market)
        if result.success:
            closed.append({"market": market, "pnl": result.realized_pnl})
            add_log(f"🚨 Emergency close: {market} | PnL: ${result.realized_pnl:+.2f}", "warn")

    if app_state["active_position"]:
        app_state["active_position"] = None
        state_machine.exit_trade(0, "Emergency close por usuario")

    return {"closed": closed}


@app.post("/api/recover")
async def api_recover(user: str = Depends(verify_credentials)):
    """Recovery manual desde estado ERROR o CAP."""
    success = state_machine.recover()
    return {"recovered": success, "state": state_machine.state.value}


@app.get("/api/session")
async def api_session(user: str = Depends(verify_credentials)):
    """Métricas de la sesión diaria."""
    return JSONResponse(risk_engine.get_session_state())


@app.get("/api/decisions")
async def api_decisions(user: str = Depends(verify_credentials)):
    """Log de decisiones del bot."""
    return JSONResponse(app_state["decisions_log"][:50])


# ══════════════════════════════════════════════════════════
#  🚀 ENTRY POINT
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    uvicorn.run("main_v3:app", host="0.0.0.0", port=8000, reload=False, log_level="info")

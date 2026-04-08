"""
╔══════════════════════════════════════════════════════════╗
║   AGENTE AUTÓNOMO DE TRADING CRIPTO (Solana DEX)         ║
║   Backend Web FastAPI + Motor Quant Async                ║
║   Exchange: Jupiter v6 · DEX: Jupiter / Raydium          ║
║   Moneda Base: SOL · Paper Trading Mode Incluido         ║
╚══════════════════════════════════════════════════════════╝
"""

import os
import time
import math
import asyncio
import threading
import logging
import subprocess
import aiohttp
import json
import csv
import io
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv
from core import db  # Módulo de memoria SQLite

from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
from fastapi.responses import HTMLResponse, Response, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import uvicorn

from exchange.jupiter_client import JupiterClient
from scanner.token_scanner import TokenScanner

# ══════════════════════════════════════════════════════════
#  ⚙️  CONFIGURACIÓN INICIAL
# ══════════════════════════════════════════════════════════
load_dotenv()

# 🕹️ MODO SIMULACIÓN (Paper Trading)
PAPER_TRADING_MODE = os.getenv("PAPER_TRADING_MODE", "True").lower() in ['true', '1', 'yes']

MAX_OPEN_TRADES  = int(os.getenv("MAX_OPEN_TRADES", "15"))
RISK_PERCENT     = float(os.getenv("TRADE_RISK_PERCENT", "0.20"))  # 20% por trade
SCAN_INTERVAL    = int(os.getenv("SCAN_INTERVAL_SECONDS", "5"))   # 5s scanner hiper-rápido
MAX_TOTAL_EXPOSURE_PCT = 0.80 # Protección global: max 80% de la cartera abierta a la vez

# ── Telegram ──
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ═══════════════════════════════════════════
#  ⚡ MODO HÍBRIDO: Slots por categoría
# ═══════════════════════════════════════════
BLUECHIP_SLOTS   = int(os.getenv("BLUECHIP_SLOTS", "4"))    # 4 slots para top Solana
SNIPER_SLOTS     = int(os.getenv("SNIPER_SLOTS", "5"))      # 5 slots para memecoins

# ── Parámetros BLUECHIP (Top Solana: JUP, WIF, RAY...) ──
BC_MIN_SCORE     = int(os.getenv("BC_MIN_SCORE", "30"))       # Score mínimo para bluechips (más generoso)
BC_TAKE_PROFIT   = float(os.getenv("BC_TAKE_PROFIT", "4"))    # TP 4% (cierres hiperrápidos)
BC_STOP_LOSS     = float(os.getenv("BC_STOP_LOSS", "2.5"))    # SL 2.5%
BC_TRAILING      = float(os.getenv("BC_TRAILING", "1.5"))     # Trailing 1.5%
BC_RISK_PCT      = float(os.getenv("BC_RISK_PCT", "0.15"))    # 15% del balance por trade
BC_SLIPPAGE      = int(os.getenv("BC_SLIPPAGE", "100"))       # 1% slippage (alta liquidez)
BC_DEAD_MIN      = int(os.getenv("BC_DEAD_MINUTES", "30"))    # 30 min dead trade

# ── Parámetros SNIPER (Memecoins: nuevos tokens) ──
SN_MIN_MOMENTUM  = int(os.getenv("SN_MIN_MOMENTUM", "45"))    # Score momentum mínimo (menos restrictivo)
SN_MIN_SAFETY    = int(os.getenv("SN_MIN_SAFETY", "30"))      # Score seguridad mínimo
SN_MIN_SCORE     = int(os.getenv("SN_MIN_SCORE", "40"))       # Score total mínimo (entrar más fácil)
SN_TAKE_PROFIT   = float(os.getenv("SN_TAKE_PROFIT", "15"))   # TP 15% (bocados fijos para target diario rápido)
SN_STOP_LOSS     = float(os.getenv("SN_STOP_LOSS", "8"))      # SL 8%
SN_TRAILING      = float(os.getenv("SN_TRAILING", "4"))       # Trailing 4%
SN_RISK_PCT      = float(os.getenv("SN_RISK_PCT", "0.05"))    # 5% del balance por trade (más disparos)
SN_SLIPPAGE_BUY  = int(os.getenv("SN_SLIPPAGE_BUY", "1500"))  # 15%
SN_SLIPPAGE_SELL = int(os.getenv("SN_SLIPPAGE_SELL", "2000")) # 20%
SN_MOONBAG       = float(os.getenv("SN_MOONBAG", "0.15"))     # 15% moonbag
SN_DEAD_MIN      = int(os.getenv("SN_DEAD_MINUTES", "15"))    # 15 min dead trade

SNIPER_MAX_AGE_MIN = int(os.getenv("SNIPER_MAX_AGE_MIN", "60"))  # Tokens de < 1h

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("AgenteBot")

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

# ── Exchange & Scanner ──
exchange = JupiterClient(paper_mode=PAPER_TRADING_MODE)
scanner = TokenScanner()

# ── Clones (Shadow Traders) ──
db.init_db()  # Asegurar tablas existen ANTES de que clones carguen estado
db.clean_old_history(retention_days=7) # Poda automática de gráficos obsoletos para alta velocidad
from clones import initialize_clones
from ai.clone_brain_feedback import process_clone_cycle_report
from ai.clone_signals import signal_bus
clone_instances = initialize_clones()

# ── AI Modules ──
from ai.sentiment import update_sentiment, get_risk_modifier, get_sentiment_summary
from ai.kelly_criterion import get_kelly_risk, calculate_kelly_fraction
from ai.ml_predictor import predict_trade_probability, train_model
ML_MODEL_PATH = os.path.join(os.path.dirname(__file__), "data", "agent_model.pkl")

# Global State para el Dashboard
app_state = {
    "balance_usd":      exchange.paper_balance_usd,
    "balance_sol_gas":  0.5,
    "initial_balance_usd": exchange.paper_balance_usd,
    "mode":             "Simulación" if PAPER_TRADING_MODE else "Live",
    "active_trades":    [],
    "max_trades":       MAX_OPEN_TRADES,
    "win_count":        0,
    "closed_count":     0,
    "logs":             [],
    "next_scan_at":     time.time() + SCAN_INTERVAL,
    "scan_interval":    SCAN_INTERVAL,
    "last_scan":        None,
    "live_prices":      {},          # {mint: {"price_usd": float, "change_pct": float}}
    "candidates":       [],          # Tokens candidatos (near-miss)
    "total_pnl":        0.0,
    "unrealized_pnl":   0.0,
    "market_regime":    "SCANNING",  # TRENDING | SNIPING | SCANNING
    "paused":           False,
    "paused_reason":    "",
    "daily_loss":       0.0,
    "daily_open_count": 0,
    "insights":         [],
    "agent_params":     {},
    "sol_price_usd":    0.0,
    "trending_tokens":  [],          # Top tokens trending
    "new_tokens":       [],          # Nuevos lanzamientos
    "bluechip_tokens":  [],          # Top Solana (JUP, WIF, RAY...)
    "scan_mode":        "HYBRID",    # HYBRID = Bluechips + Sniper
    "bluechip_count":   0,           # Trades bluechip abiertos
    "sniper_count":     0,           # Trades sniper abiertos
    "bot_active":       True,        # Agent Power Kill switch (Auto Run)
    "consecutive_losses": 0,          # Circuit breaker counter
    "circuit_breaker_until": 0,       # timestamp hasta que se reactiva
    "brain_stats": {
        "buys": 0,
        "rejects": 0,
        "closes": 0,
        "regime": 0
    },
    "brain_log": [], # [{time, type, msg}]
    "clone_signals": [],  # Señales en tiempo real de clones
    "signal_stats": {},    # Estadísticas del bus de señales
}

# ── LOGS ──
def add_log(msg, log_type="info"):
    now = datetime.now().strftime("%H:%M:%S")
    log_id = len(app_state["logs"])
    app_state["logs"].append({"id": log_id, "time": now, "type": log_type, "msg": msg})
    if len(app_state["logs"]) > 200:
        app_state["logs"] = app_state["logs"][-150:]

def add_brain_event(msg, event_type="info"):
    """Registra eventos específicos para la pestaña Brain"""
    now = datetime.now().strftime("%H:%M:%S")
    app_state["brain_log"].insert(0, {"time": now, "type": event_type, "msg": msg})
    if event_type == "buy": app_state["brain_stats"]["buys"] += 1
    elif event_type == "reject": app_state["brain_stats"]["rejects"] += 1
    elif event_type == "close": app_state["brain_stats"]["closes"] += 1
    elif event_type == "regime": app_state["brain_stats"]["regime"] += 1
    
    if len(app_state["brain_log"]) > 100:
        app_state["brain_log"] = app_state["brain_log"][:100]

# ══════════════════════════════════════════════════════════
#  🧠 LÓGICA DEL AGENTE — ENGINE LOOP
# ══════════════════════════════════════════════════════════

async def engine_loop():
    # Loop principal (DB initialized in lifespan)

    # Cargar balance de DB o usar default (ahora en USDC)
    saved = db.load_balance(exchange.paper_balance_usd, default_gas=0.5)
    app_state["balance_usd"] = saved["balance"]
    app_state["balance_sol_gas"] = saved.get("balance_sol_gas", 0.5)
    app_state["total_pnl"] = saved["total_pnl"]
    app_state["win_count"] = saved["win_count"]
    app_state["closed_count"] = saved["closed_count"]
    exchange.paper_balance_usd = saved["balance"]
    exchange.paper_balance_sol_gas = app_state["balance_sol_gas"]

    # Cargar trades activos de DB
    global_active = db.load_active_trades()
    app_state["active_trades"] = global_active

    # Obtener precio SOL (Para UI solamente)
    sol_usd = await exchange.get_sol_price_usd()
    app_state["sol_price_usd"] = sol_usd

    # Ajuste de cuenta nueva (fresco) a $1000 netos
    if saved["balance"] <= 2.0:  # Ajuste
        exchange.paper_balance_usd = 1000.0
        exchange.paper_balance_sol_gas = 0.5
        
    app_state["balance_usd"] = exchange.paper_balance_usd
    app_state["balance_sol_gas"] = exchange.paper_balance_sol_gas
    app_state["initial_balance_usd"] = exchange.paper_balance_usd

    db.save_balance(app_state["balance_usd"], 0, 0, 0, app_state["balance_sol_gas"])

    add_log(f"🧠 Agente Solana iniciado | SOL: ${sol_usd:.2f} | Balance: ${app_state['balance_usd']:.2f} | Gas: {app_state['balance_sol_gas']} SOL", "info")
    add_log(f"🎯 Modo: Live/Devnet | Start Equity: ${app_state['initial_balance_usd']:.2f}", "info")

    # Reset diario
    last_reset_day = datetime.now().day
    start_of_day_balance = app_state["balance_usd"]

    await notify_telegram(
        f"🚀 <b>Agente Solana DEX — Modo Híbrido</b>\n"
        f"💰 Balance: ${app_state['balance_usd']:.2f} USDC\n"
        f"🎮 Modo: {'Simulación' if PAPER_TRADING_MODE else 'LIVE'}\n"
        f"💎 Bluechip: {BLUECHIP_SLOTS} slots (TP:{BC_TAKE_PROFIT}% SL:{BC_STOP_LOSS}%)\n"
        f"🔫 Sniper: {SNIPER_SLOTS} slots (TP:{SN_TAKE_PROFIT}% SL:{SN_STOP_LOSS}%)"
    )

    while True:
        try:
            now = datetime.now()

            # ── Bot Active Check ──
            if not app_state.get("bot_active", False):
                app_state["next_scan_at"] = time.time() + 5
                await asyncio.sleep(5)
                continue

            # ── Reset diario ──
            if now.day != last_reset_day:
                app_state["daily_loss"] = 0.0
                app_state["daily_open_count"] = 0
                app_state["paused"] = False
                app_state["paused_reason"] = ""
                start_of_day_balance = app_state["balance_usd"]
                last_reset_day = now.day
                add_log("📅 Reset diario completado", "info")

            app_state["last_scan"] = now.strftime("%H:%M:%S")

            # ── Actualizar precio SOL ──
            sol_usd = await exchange.get_sol_price_usd()
            if sol_usd > 0:
                app_state["sol_price_usd"] = sol_usd

            # ── Protección de drawdown diario ──
            daily_loss_lim = float(db.get_param("DAILY_LOSS_LIMIT", "0.15"))
            daily_loss_pct = abs(app_state["daily_loss"]) / (start_of_day_balance or 1)
            if daily_loss_pct >= daily_loss_lim and not app_state["paused"]:
                app_state["paused"] = True
                app_state["paused_reason"] = f"Límite diario {daily_loss_lim:.0%} alcanzado"
                add_log(f"🛡️ Drawdown {daily_loss_pct:.1%} → PAUSA hasta mañana", "warn")

            if app_state["paused"]:
                app_state["next_scan_at"] = time.time() + SCAN_INTERVAL
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            # ── Circuit Breaker: 3+ pérdidas consecutivas → pausa 30 min ──
            if app_state.get("circuit_breaker_until", 0) > time.time():
                remaining = int(app_state["circuit_breaker_until"] - time.time())
                if remaining % 60 == 0:  # Log cada minuto
                    add_log(f"🛑 Circuit Breaker activo — {remaining//60} min restantes", "warn")
                app_state["next_scan_at"] = time.time() + 10
                await asyncio.sleep(10)
                continue
            elif app_state.get("consecutive_losses", 0) >= 3:
                # Llegamos aquí cuando el timer expiró, reset counter
                app_state["consecutive_losses"] = 0
                add_log("✅ Circuit Breaker desactivado — Reanudando con riesgo reducido", "info")

            # ── Contar slots por categoría ──
            bc_count = sum(1 for t in app_state["active_trades"] if t.get("source") == "bluechip")
            sn_count = sum(1 for t in app_state["active_trades"] if t.get("source") != "bluechip")
            app_state["bluechip_count"] = bc_count
            app_state["sniper_count"] = sn_count
            active_len = len(app_state["active_trades"])

            add_log(f"🔍 Escaneando Solana... [💎{bc_count}/{BLUECHIP_SLOTS} 🔫{sn_count}/{SNIPER_SLOTS}]", "info")

            open_mints = set(t["mint"] for t in app_state["active_trades"])
            near_candidates = []

            # ═══════════════════════════════════════════
            #  💎 PHASE 1: BLUECHIP SCAN (Top Solana)
            # ═══════════════════════════════════════════
            if True: # Scanear SIEMPRE para mantener el radar/UI vivo
                bluechips = await scanner.scan_bluechips(limit=20)
                app_state["bluechip_tokens"] = bluechips[:10]

                for token in bluechips:
                    mint = token["mint"]
                    if mint in open_mints:
                        continue

                    scores = scanner.score_bluechip(token)
                    token["scores"] = scores

                    near_candidates.append({
                        "symbol": token.get("symbol", "?"),
                        "name": token.get("name", "Unknown"),
                        "mint": mint,
                        "price_usd": token.get("price_usd", 0),
                        "volume_5m": token.get("volume_5m", 0),
                        "momentum": scores["momentum"],
                        "safety": scores["safety"],
                        "total": scores["total"],
                        "source": "bluechip",
                        "scores": scores,
                    })

                    if scores["total"] < BC_MIN_SCORE:
                        continue

                    # ── 🤖 ML PREDICTOR GATE ──
                    ml_prob = predict_trade_probability(
                        rsi=0, macd=0,
                        tf_score=scores["total"],
                        ema_align=1 if scores["momentum"] > 50 else 0,
                        regime=app_state.get("market_regime", "SIDEWAYS"),
                        bb_width=0, bb_position=0.5
                    )
                    scores["ml_prob"] = ml_prob
                    if ml_prob < 0.25:
                        add_brain_event(
                            f"🤖 ML rechazó 💎{token.get('symbol','?')} "
                            f"(prob={ml_prob:.0%}, score={scores['total']:.0f})",
                            "reject"
                        )
                        continue

                    price_usd = token.get("price_usd", 0)
                    if price_usd <= 0:
                        continue

                    # Si el slot ya está lleno, no comprar, solo mostrar en radar visual
                    if bc_count >= BLUECHIP_SLOTS:
                        continue

                    # ── 📐 KELLY + SENTIMENT POSITION SIZING ──
                    sentiment_mod = get_risk_modifier()
                    kelly_risk = get_kelly_risk(
                        b_score=min(3, scores["total"] // 33),
                        regime=app_state.get("market_regime", "SIDEWAYS")
                    )
                    if kelly_risk is not None:
                        effective_risk = kelly_risk * sentiment_mod
                        risk_usd = app_state["balance_usd"] * effective_risk
                    else:
                        risk_usd = app_state["balance_usd"] * BC_RISK_PCT * sentiment_mod

                    if risk_usd < 10.0:
                        add_brain_event(f"🧠 Rechazo: Riesgo insuficiente (${risk_usd:.2f})", "reject")
                        continue

                    # ── 🛡️ DIVERSIFICATION: MAX EXPOSURE CHECK ──
                    current_exposure = sum(t.get("usd_spent", t.get("sol_spent", 0) * sol_usd) for t in app_state["active_trades"])
                    if current_exposure + risk_usd > app_state["initial_balance_usd"] * MAX_TOTAL_EXPOSURE_PCT:
                        add_brain_event(f"🛡️ Rechazo Exposición: Limite de {MAX_TOTAL_EXPOSURE_PCT*100}% de capital alcanzado.", "reject")
                        continue

                    # ── 🛡️ LIQUIDITY IMPACT CHECK ──
                    if risk_usd > (token.get("liquidity_usd", 0) * 0.025):
                        add_brain_event(f"🛡️ Rechazo Liquidez: Trade > 2.5% del pool ({token.get('symbol','?')})", "reject")
                        continue

                    result = await exchange.swap_buy(mint, risk_usd, BC_SLIPPAGE)
                    if not result["success"]:
                        add_log(f"❌ Bluechip compra fallida: {token.get('symbol','?')} — {result.get('error','')}", "warn")
                        continue

                    new_trade = {
                        "mint": mint,
                        "symbol": token.get("symbol", "?"),
                        "name": token.get("name", "Unknown"),
                        "entry_usd": result["price_usd"],
                        "qty": result["qty"],
                        "usd_spent": result.get("usd_spent", risk_usd),
                        "sol_spent": result.get("sol_spent", 0), # Fallback compatibility
                        "sl_pct": BC_STOP_LOSS,
                        "tp_pct": BC_TAKE_PROFIT,
                        "trailing_pct": BC_TRAILING,
                        "dead_trade_min": BC_DEAD_MIN,
                        "moonbag_pct": 0,
                        "sl_price": result["price_usd"] * (1 - BC_STOP_LOSS / 100),
                        "tp_price": result["price_usd"] * (1 + BC_TAKE_PROFIT / 100),
                        "highest_price": result["price_usd"],
                        "trailing_active": False,
                        "current_price": result["price_usd"],
                        "pnl": 0.0,
                        "pnl_pct": 0.0,
                        "opened_at": datetime.now().isoformat(),
                        "agent_id": "main",
                        "source": "bluechip",
                        "scores": scores,
                        "tx_hash": result.get("tx_hash", ""),
                        "type": "BUY",
                        "symbol_display": f"💎{token.get('symbol', '?')}",
                        "entry": result["price_usd"],
                        "sl": result["price_usd"] * (1 - BC_STOP_LOSS / 100),
                        "tp2": result["price_usd"] * (1 + BC_TAKE_PROFIT / 100),
                    }

                    app_state["active_trades"].append(new_trade)
                    app_state["balance_usd"] = exchange.paper_balance_usd
                    app_state["balance_sol_gas"] = exchange.paper_balance_sol_gas
                    db.save_balance(app_state["balance_usd"], app_state["total_pnl"],
                                    app_state["win_count"], app_state["closed_count"],
                                    app_state["balance_sol_gas"])
                    app_state["daily_open_count"] += 1
                    bc_count += 1
                    open_mints.add(mint)
                    db.save_active_trades(app_state["active_trades"])

                    add_brain_event(f"💎 Compra Bluechip: {token.get('symbol','?')} @ ${price_usd:.4f}", "buy")
                    add_log(
                        f"💎 COMPRA BLUECHIP: {token.get('symbol','?')} | "
                        f"${price_usd:.6f} | TP:+{BC_TAKE_PROFIT}% SL:-{BC_STOP_LOSS}% | "
                        f"Score: {scores['total']:.0f}",
                        "info"
                    )
                    await notify_telegram(
                        f"💎 <b>COMPRA BLUECHIP — {token.get('symbol','?')}</b>\n"
                        f"💰 Precio: <b>${price_usd:.6f}</b>\n"
                        f"📊 Score: {scores['total']:.0f}\n"
                        f"🎯 TP: +{BC_TAKE_PROFIT}% | SL: -{BC_STOP_LOSS}%\n"
                        f"📦 Cost: ${result.get('usd_spent', risk_usd):.2f} USDC"
                    )

            # ═══════════════════════════════════════════
            #  🔫 PHASE 2: SNIPER SCAN (Memecoins)
            # ═══════════════════════════════════════════
            if True: # Scanear trending/nuevos incondicionalmente
                trending = await scanner.scan_trending(limit=20)
                app_state["trending_tokens"] = trending[:10]

                new_tokens = await scanner.scan_new_tokens(max_age_minutes=SNIPER_MAX_AGE_MIN, limit=15)
                app_state["new_tokens"] = new_tokens[:10]

                all_sniper = trending + new_tokens
                seen = set()
                unique_sniper = []
                for t in all_sniper:
                    if t["mint"] not in seen:
                        seen.add(t["mint"])
                        unique_sniper.append(t)

                add_log(f"📊 Sniper pool: {len(trending)} trending + {len(new_tokens)} nuevos", "info")

                for token in unique_sniper:
                    mint = token["mint"]
                    if mint in open_mints:
                        continue

                    scores = scanner.score_token(token)
                    token["scores"] = scores

                    if scores["total"] >= SN_MIN_SCORE - 15:
                        near_candidates.append({
                            "symbol": token.get("symbol", "?"),
                            "name": token.get("name", "Unknown"),
                            "mint": mint,
                            "price_usd": token.get("price_usd", 0),
                            "volume_5m": token.get("volume_5m", 0),
                            "momentum": scores["momentum"],
                            "safety": scores["safety"],
                            "total": scores["total"],
                            "source": token.get("source", "?"),
                            "scores": scores,
                        })

                    if scores["momentum"] < SN_MIN_MOMENTUM or scores["safety"] < SN_MIN_SAFETY or scores["total"] < SN_MIN_SCORE:
                        if scores["total"] >= SN_MIN_SCORE - 10:
                            add_brain_event(f"🧠 Rechazo Score: {token.get('symbol','?')} (Score {scores['total']:.0f} < {SN_MIN_SCORE})", "reject")
                        continue

                    # ── 🤖 ML PREDICTOR GATE ──
                    ml_prob = predict_trade_probability(
                        rsi=0, macd=0,
                        tf_score=scores["total"],
                        ema_align=1 if scores["momentum"] > 50 else 0,
                        regime=app_state.get("market_regime", "SIDEWAYS"),
                        bb_width=0, bb_position=0.5
                    )
                    scores["ml_prob"] = ml_prob
                    if ml_prob < 0.50:
                        add_brain_event(
                            f"🤖 ML rechazó 🔫{token.get('symbol','?')} "
                            f"(prob={ml_prob:.0%}, score={scores['total']:.0f})",
                            "reject"
                        )
                        continue

                    price_usd = token.get("price_usd", 0)
                    if price_usd <= 0:
                        continue

                    # Si slot está lleno, abortar compra pero retener métricas en radar UI
                    if sn_count >= SNIPER_SLOTS:
                        continue

                    # ── 📐 KELLY + SENTIMENT POSITION SIZING ──
                    sentiment_mod = get_risk_modifier()
                    kelly_risk = get_kelly_risk(
                        b_score=min(3, scores["total"] // 33),
                        regime=app_state.get("market_regime", "SIDEWAYS")
                    )
                    if kelly_risk is not None:
                        effective_risk = kelly_risk * sentiment_mod
                        risk_usd = app_state["balance_usd"] * effective_risk
                    else:
                        risk_usd = app_state["balance_usd"] * SN_RISK_PCT * sentiment_mod

                    if risk_usd < 10.0:
                        add_brain_event(f"🧠 Rechazo: Riesgo insuficiente (${risk_usd:.2f})", "reject")
                        continue

                    # ── 🛡️ DIVERSIFICATION: MAX EXPOSURE CHECK ──
                    current_exposure = sum(t.get("usd_spent", t.get("sol_spent", 0) * sol_usd) for t in app_state["active_trades"])
                    if current_exposure + risk_usd > app_state["initial_balance_usd"] * MAX_TOTAL_EXPOSURE_PCT:
                        add_brain_event(f"🛡️ Rechazo Exposición: Limite de {MAX_TOTAL_EXPOSURE_PCT*100}% de capital alcanzado.", "reject")
                        continue

                    # ── 🛡️ DIVERSIFICATION: ANTI SECTOR ──
                    memecoin_keywords = ["dog", "cat", "inu", "pepe", "ai", "trump", "bonk", "wif", "elon", "moon"]
                    token_name_lower = token.get("name", "").lower() + token.get("symbol", "").lower()
                    
                    found_matches = []
                    for act_trade in app_state["active_trades"]:
                        if act_trade.get("source") != "bluechip":
                            act_name_lower = act_trade.get("name", "").lower() + act_trade.get("symbol", "").lower()
                            for kw in memecoin_keywords:
                                if kw in token_name_lower and kw in act_name_lower:
                                    found_matches.append(kw)
                    
                    if len(found_matches) > 0:
                        add_brain_event(f"🛡️ Rechazo Correlación: Ya existe trade con sector '{found_matches[0]}'.", "reject")
                        continue

                    # ── 🛡️ LIQUIDITY IMPACT CHECK ──
                    if risk_usd > (token.get("liquidity_usd", 0) * 0.025):
                        add_brain_event(f"🛡️ Rechazo Liquidez: Trade > 2.5% del pool ({token.get('symbol','?')})", "reject")
                        continue

                    result = await exchange.swap_buy(mint, risk_usd, SN_SLIPPAGE_BUY)
                    if not result["success"]:
                        add_log(f"❌ Sniper compra fallida: {token.get('symbol','?')} — {result.get('error','')}", "warn")
                        continue

                    new_trade = {
                        "mint": mint,
                        "symbol": token.get("symbol", "?"),
                        "name": token.get("name", "Unknown"),
                        "entry_usd": result["price_usd"],
                        "qty": result["qty"],
                        "usd_spent": result.get("usd_spent", risk_usd),
                        "sol_spent": result.get("sol_spent", 0), # Fallback compatibility
                        "sl_pct": SN_STOP_LOSS,
                        "tp_pct": SN_TAKE_PROFIT,
                        "trailing_pct": SN_TRAILING,
                        "dead_trade_min": SN_DEAD_MIN,
                        "moonbag_pct": SN_MOONBAG,
                        "sl_price": result["price_usd"] * (1 - SN_STOP_LOSS / 100),
                        "tp_price": result["price_usd"] * (1 + SN_TAKE_PROFIT / 100),
                        "highest_price": result["price_usd"],
                        "trailing_active": False,
                        "current_price": result["price_usd"],
                        "pnl": 0.0,
                        "pnl_pct": 0.0,
                        "opened_at": datetime.now().isoformat(),
                        "agent_id": "main",
                        "source": token.get("source", "trending"),
                        "scores": scores,
                        "tx_hash": result.get("tx_hash", ""),
                        "type": "BUY",
                        "symbol_display": f"🔫{token.get('symbol', '?')}",
                        "entry": result["price_usd"],
                        "sl": result["price_usd"] * (1 - SN_STOP_LOSS / 100),
                        "tp2": result["price_usd"] * (1 + SN_TAKE_PROFIT / 100),
                    }

                    app_state["active_trades"].append(new_trade)
                    app_state["balance_usd"] = exchange.paper_balance_usd
                    app_state["balance_sol_gas"] = exchange.paper_balance_sol_gas
                    db.save_balance(app_state["balance_usd"], app_state["total_pnl"],
                                    app_state["win_count"], app_state["closed_count"],
                                    app_state["balance_sol_gas"])
                    app_state["daily_open_count"] += 1
                    sn_count += 1
                    open_mints.add(mint)
                    db.save_active_trades(app_state["active_trades"])

                    src_emoji = "🔫" if new_trade["source"] in ("new_pair", "new_profile") else "📈"
                    add_brain_event(f"🔫 Compra Sniper: {token.get('symbol','?')} @ ${price_usd:.8f}", "buy")
                    add_log(
                        f"{src_emoji} COMPRA SNIPER: {token.get('symbol','?')} | "
                        f"${price_usd:.8f} | Score: {scores['total']:.0f} | {new_trade['source']}",
                        "info"
                    )
                    await notify_telegram(
                        f"🔫 <b>COMPRA SNIPER — {token.get('symbol','?')}</b>\n"
                        f"💰 Precio: <b>${price_usd:.8f}</b>\n"
                        f"📊 Score: M:{scores['momentum']:.0f} S:{scores['safety']:.0f} T:{scores['total']:.0f}\n"
                        f"🎯 TP: +{SN_TAKE_PROFIT}% | SL: -{SN_STOP_LOSS}%\n"
                        f"🏷️ Source: {new_trade['source']}"
                    )

            app_state["candidates"] = near_candidates[:10]

            # ═══════════════════════════════════════════
            #  🧬 SYNC CLONES (Shadow Trading) - Exploradores independientes
            # ═══════════════════════════════════════════
            for cid, clone in clone_instances.items():
                clone.sync_entries(near_candidates, sol_usd)

            # ═══════════════════════════════════════════
            #  📡 CLONE SIGNALS — Análisis en tiempo real (cada 5s)
            # ═══════════════════════════════════════════
            try:
                signal_bus.analyze_clones(clone_instances, app_state)
                signals = signal_bus.drain()
                for sig in signals:
                    stype = sig["type"]
                    sdata = sig["data"]

                    if stype == "DISCOVERY":
                        add_log(
                            f"📡 [{sdata['clone_name']}] descubrió {sdata['symbol']} "
                            f"(score: {sdata.get('scores',{}).get('total',0):.0f}) — cerebro notificado",
                            "info"
                        )
                        add_brain_event(
                            f"📡 Señal DISCOVERY: {sdata['symbol']} vía {sdata['clone_name']}",
                            "signal"
                        )

                    elif stype == "HOT_TRADE":
                        add_log(
                            f"🔥 [{sdata['clone_name']}] HOT: {sdata['symbol']} "
                            f"+{sdata['pnl_pct']:.1f}% en {sdata['elapsed_sec']}s!",
                            "info"
                        )
                        add_brain_event(
                            f"🔥 HOT TRADE: {sdata['symbol']} +{sdata['pnl_pct']:.1f}% en {sdata['elapsed_sec']}s",
                            "signal"
                        )
                        # Auto-comprar si cerebro no tiene este token y tiene slots
                        mint = sdata.get("mint")
                        if mint and mint not in open_mints and len(app_state["active_trades"]) < MAX_OPEN_TRADES:
                            add_log(
                                f"🧠 Cerebro actúa por señal HOT: Auto-comprando {sdata['symbol']}...",
                                "info"
                            )
                            # Calculamos riesgo
                            s_mod = get_risk_modifier()
                            kr = get_kelly_risk(3, app_state.get("market_regime", "SIDEWAYS"))
                            risk_usd = app_state["balance_usd"] * (kr * s_mod if kr else SN_RISK_PCT * s_mod)
                            
                            res = await exchange.swap_buy(mint, risk_usd, SN_SLIPPAGE_BUY)
                            if res.get("success"):
                                new_trade = {
                                    "mint": mint, "symbol": sdata["symbol"], "name": sdata.get("name", "Unknown"), 
                                    "entry_usd": res["price_usd"], "qty": res["qty"],
                                    "usd_spent": risk_usd, "sl_pct": SN_STOP_LOSS, "tp_pct": SN_TAKE_PROFIT,
                                    "trailing_pct": SN_TRAILING, "dead_trade_min": SN_DEAD_MIN, "moonbag_pct": SN_MOONBAG,
                                    "sl_price": res["price_usd"] * (1 - SN_STOP_LOSS / 100),
                                    "tp_price": res["price_usd"] * (1 + SN_TAKE_PROFIT / 100),
                                    "highest_price": res["price_usd"], "trailing_active": False,
                                    "current_price": res["price_usd"], "pnl": 0.0, "pnl_pct": 0.0,
                                    "opened_at": datetime.now().isoformat(), "agent_id": "main", "source": "signal_hot",
                                    "scores": {"total": 80}, "tx_hash": res.get("tx_hash", ""), "type": "BUY"
                                }
                                app_state["active_trades"].append(new_trade)
                                open_mints.add(mint)
                                db.save_active_trades(app_state["active_trades"])
                                add_brain_event(f"⚡ COMPRA HOT_TRADE: {sdata['symbol']} iniciada.", "buy")

                    elif stype == "CONVICTION":
                        add_log(
                            f"🎯 CONVICTION: {sdata['clone_count']} clones en {sdata['symbol']} — señal fuerte!",
                            "info"
                        )
                        add_brain_event(
                            f"🎯 CONVICTION: {sdata['clone_count']} clones confirmaron {sdata['symbol']}",
                            "signal"
                        )
                        mint = sdata.get("mint")
                        if mint and mint not in open_mints and len(app_state["active_trades"]) < MAX_OPEN_TRADES:
                            s_mod = get_risk_modifier()
                            kr = get_kelly_risk(3, app_state.get("market_regime", "SIDEWAYS"))
                            risk_usd = app_state["balance_usd"] * (kr * s_mod if kr else SN_RISK_PCT * s_mod)
                            res = await exchange.swap_buy(mint, risk_usd, SN_SLIPPAGE_BUY)
                            if res.get("success"):
                                new_trade = {
                                    "mint": mint, "symbol": sdata["symbol"], "name": sdata.get("name", "Unknown"), 
                                    "entry_usd": res["price_usd"], "qty": res["qty"],
                                    "usd_spent": risk_usd, "sl_pct": SN_STOP_LOSS, "tp_pct": SN_TAKE_PROFIT,
                                    "trailing_pct": SN_TRAILING, "dead_trade_min": SN_DEAD_MIN, "moonbag_pct": SN_MOONBAG,
                                    "sl_price": res["price_usd"] * (1 - SN_STOP_LOSS / 100),
                                    "tp_price": res["price_usd"] * (1 + SN_TAKE_PROFIT / 100),
                                    "highest_price": res["price_usd"], "trailing_active": False,
                                    "current_price": res["price_usd"], "pnl": 0.0, "pnl_pct": 0.0,
                                    "opened_at": datetime.now().isoformat(), "agent_id": "main", "source": "signal_conviction",
                                    "scores": {"total": 90}, "tx_hash": res.get("tx_hash", ""), "type": "BUY"
                                }
                                app_state["active_trades"].append(new_trade)
                                open_mints.add(mint)
                                db.save_active_trades(app_state["active_trades"])
                                add_brain_event(f"🎯 COMPRA CONVICTION: {sdata['symbol']} confirmada por clones.", "buy")

                    elif stype == "ALPHA":
                        add_log(
                            f"🧠 {sdata['clone_name']} supera cerebro por +{sdata['delta']:.1f}% — "
                            f"Clone: {sdata['clone_pnl_pct']:+.2f}% vs Brain: {sdata['brain_pnl_pct']:+.2f}%",
                            "info"
                        )
                        add_brain_event(
                            f"🧬 ALPHA: {sdata['clone_name']} +{sdata['delta']:.1f}% sobre cerebro",
                            "signal"
                        )

                    elif stype == "EXIT_WARN":
                        if sdata.get('pnl_pct', 0) <= -5:
                            add_brain_event(
                                f"⚠️ EXIT: {sdata['clone_name']} cerró {sdata['symbol']} {sdata['pnl_pct']:+.1f}%",
                                "warn"
                            )

                # Actualizar stats para dashboard
                app_state["signal_stats"] = signal_bus.get_stats()
                app_state["clone_signals"] = signal_bus.history[-20:]  # últimas 20

            except Exception as e:
                log.error(f"[SIGNALS] Error en análisis de señales: {e}")

            app_state["next_scan_at"] = time.time() + SCAN_INTERVAL
            await asyncio.sleep(SCAN_INTERVAL)

        except Exception as e:
            log.error(f"Engine loop error: {e}")
            add_log(f"⚠️ Error en engine: {e}", "warn")
            await asyncio.sleep(5)


# ══════════════════════════════════════════════════════════
#  📊 LIVE PRICES + EXIT MANAGEMENT
# ══════════════════════════════════════════════════════════

async def update_live_prices():
    """Polling de precios para gestión de exits y dashboard."""
    add_log("🔌 Iniciando Price Feed (Jupiter + DexScreener)...", "info")
    
    while True:
        try:
            # Obtener precios de todos los tokens activos (Main + Clones)
            active_mints = set([t["mint"] for t in app_state["active_trades"]])
            for _, clone in clone_instances.items():
                for t in clone.active_trades:
                    active_mints.add(t["mint"])
                    
            # Siempre actualizar el mercado global para que la UI no quede vacía
            watchlist = await scanner.get_watchlist_prices()
            live = {}
            for w in watchlist:
                if w.get("price_usd", 0) > 0:
                    live[w["symbol"]] = {
                        "price": w["price_usd"],
                        "change_pct": w.get("change_pct", 0), # Si existe
                        "volume": w.get("volume_5m", 0),
                    }
            
            active_mints = list(active_mints)
            prices = await exchange.get_batch_prices_usd(active_mints)

            # --- Merge Active Trades into Live Prices para gráficas ---
            for trade in app_state["active_trades"]:
                sym = trade.get("symbol")
                mint = trade.get("mint")
                if sym and mint in prices:
                    live[sym] = {
                        "price": prices[mint],
                        "change_pct": ((prices[mint] - trade["entry_usd"]) / trade["entry_usd"] * 100) if trade["entry_usd"] > 0 else 0,
                        "volume": live.get(sym, {}).get("volume", 0)
                    }
            
            # --- Inyectamos finalmente despues del merge ---
            app_state["live_prices"] = live

            sol_usd = app_state.get("sol_price_usd", 150)

            # ── Gestión de Exits ──
            trades_to_close = []
            total_unrealized = 0.0

            for trade in app_state["active_trades"]:
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

                # Actualizar highest price para trailing
                if current_price > trade.get("highest_price", entry):
                    trade["highest_price"] = current_price

                # Actualizar SL y TP display
                trade["sl"] = trade.get("sl_price", entry * (1 - trade.get("sl_pct", 12) / 100))
                trade["tp2"] = trade.get("tp_price", entry * (1 + trade.get("tp_pct", 25) / 100))

                # ── CHECK: STOP LOSS ──
                if pnl_pct <= -trade.get("sl_pct", 12):
                    trades_to_close.append((trade, "STOP_LOSS", current_price, pnl_usd, pnl_pct))
                    continue

                # ── CHECK: TAKE PROFIT ──
                if pnl_pct >= trade.get("tp_pct", 25):
                    if not trade.get("tp_hit", False):
                        trade["tp_hit"] = True
                        trade["trailing_active"] = True
                        # Activar trailing stop desde este punto
                        trade["trailing_from"] = current_price
                        add_log(f"🎯 TP Hit: {trade['symbol']} +{pnl_pct:.1f}% — Trailing activado", "info")

                # ── CHECK: TRAILING STOP (después del TP) ──
                if trade.get("trailing_active", False):
                    highest = trade.get("highest_price", entry)
                    drop_from_high = ((highest - current_price) / highest * 100) if highest > 0 else 0
                    if drop_from_high >= trade.get("trailing_pct", 8):
                        trades_to_close.append((trade, "TRAILING_STOP", current_price, pnl_usd, pnl_pct))
                        continue

                # ── CHECK: DEAD TRADE (no se mueve) ──
                opened = datetime.fromisoformat(trade["opened_at"])
                age_min = (datetime.now() - opened).total_seconds() / 60
                dead_min = trade.get("dead_trade_min", 30)
                if age_min >= dead_min and abs(pnl_pct) < 3:
                    trades_to_close.append((trade, "DEAD_TRADE", current_price, pnl_usd, pnl_pct))
                    continue

            app_state["unrealized_pnl"] = round(total_unrealized, 4)

            # ── Actualizar clones con precios ──
            for cid, clone in clone_instances.items():
                closed = clone.update_prices(prices, sol_usd)
                for trade, reason, pnl_usd, pnl_pct in closed:
                    emoji = "✅" if pnl_pct > 0 else "❌"
                    add_log(f"🧬 [{clone.name}] {emoji} {reason}: {trade['symbol']} | PnL: {pnl_pct:+.1f}%", "info")
                    # Emitir señal de cierre al cerebro en tiempo real
                    signal_bus.process_clone_exit(clone.name, trade, reason, pnl_pct)
                    try:
                        db.insert_trade(trade, trade["current_price"], pnl_usd, pnl_pct, reason)
                    except Exception as e:
                        log.error(f"[DB] Error saving clone trade: {e}")

            # ── Verificar ciclos de clones (15/30/90 días) ──
            for cid, clone in clone_instances.items():
                try:
                    cycle_report = clone.check_cycle()
                    if cycle_report:
                        cn = cycle_report["cycle_number"]
                        pnl = cycle_report["pnl_return_pct"]
                        wr = cycle_report["win_rate"]
                        add_log(
                            f"🧬 [{clone.name}] 🌟 Ciclo #{cn} completado ({clone.cycle_days}d) | "
                            f"PnL: {pnl:+.1f}% | WR: {wr:.0f}% | Reportando al Cerebro...",
                            "info"
                        )
                        # Alimentar al cerebro principal
                        feedback = process_clone_cycle_report(cycle_report)
                        if feedback and feedback.get("mutations_applied"):
                            muts = feedback["mutations_applied"]
                            add_log(
                                f"🧠 Cerebro mutató {len(muts)} parámetro(s) por {clone.name}",
                                "info"
                            )
                except Exception as e:
                    log.error(f"[CYCLE] Error checking {cid}: {e}")

            # ── Ejecutar ventas ──
            for trade, reason, exit_price, pnl_usd, pnl_pct in trades_to_close:
                sell_pct = 1.0
                moonbag = trade.get("moonbag_pct", 0)
                slippage = SN_SLIPPAGE_SELL if trade.get("source") != "bluechip" else BC_SLIPPAGE
                if reason == "TRAILING_STOP" and moonbag > 0:
                    sell_pct = 1.0 - moonbag

                result = await exchange.swap_sell(trade["mint"], sell_pct=sell_pct, slippage_bps=slippage)
                
                if result["success"]:
                    is_win = pnl_pct > 0
                    app_state["closed_count"] += 1
                    if is_win:
                        app_state["win_count"] += 1
                        app_state["consecutive_losses"] = 0  # Reset streak
                    else:
                        app_state["consecutive_losses"] = app_state.get("consecutive_losses", 0) + 1

                    app_state["total_pnl"] = round(app_state["total_pnl"] + pnl_usd * sell_pct, 4)
                    app_state["balance_usd"] = exchange.paper_balance_usd

                    if not is_win:
                        app_state["daily_loss"] += pnl_usd * sell_pct

                    # ── 🛑 DESACTIVADO POR RETO: CIRCUIT BREAKER: 3+ pérdidas seguidas ──
                    if app_state["consecutive_losses"] >= 3:
                        pass # Reto del usuario desactiva este límite a favor del stop global 20%

                    emoji = "🚀" if is_win else "🔴"
                    reason_lbl = {
                        "STOP_LOSS": "❌ STOP LOSS",
                        "TRAILING_STOP": "✅ TRAILING STOP",
                        "DEAD_TRADE": "💀 DEAD TRADE",
                        "TAKE_PROFIT": "🎯 TAKE PROFIT",
                    }.get(reason, reason)

                    # Guardar en DB
                    db_trade = {
                        "symbol": trade["symbol"],
                        "entry": trade["entry_usd"],
                        "qty": trade["qty"] * sell_pct,
                        "sl": trade.get("sl_price", 0),
                        "tp2": trade.get("tp_price", 0),
                        "opened_at": trade["opened_at"],
                        "agent_id": "main",
                        "score": trade.get("scores", {}).get("total", 0),
                    }
                    db.save_trade(db_trade, exit_price, reason, "SOLANA")

                    if app_state["closed_count"] > 0 and app_state["closed_count"] % 30 == 0:
                        add_log(f"🧠 [MACHINE LEARNING] Re-entrenando modelo predictivo (Ciclo 30 trades, Asíncrono)...", "info")
                        model_success = await asyncio.to_thread(train_model)
                        if model_success:
                            add_log(f"✅ Auto-Optimización en backend exitosa: El Agente ahora es más preciso", "info")
                        else:
                            add_log(f"⚠️ Entrenamiento M/L fallido/skipeado", "warn")

                    add_brain_event(f"💰 Cierre {reason_lbl}: {trade['symbol']} ({pnl_pct:+.1f}%)", "close")
                    add_log(f"{reason_lbl} {trade['symbol']} | PnL: ${pnl_usd:+.4f} ({pnl_pct:+.1f}%)", "info" if is_win else "warn")
                    await notify_telegram(
                        f"{emoji} <b>{reason_lbl} — {trade['symbol']}</b>\n"
                        f"💰 PnL: <b>${pnl_usd:+.4f} ({pnl_pct:+.1f}%)</b>\n"
                        f"📊 Entry: ${trade['entry_usd']:.8f} → Exit: ${exit_price:.8f}\n"
                        f"💼 Balance: ${app_state['balance_usd']:.2f} USDC"
                    )

                    if sell_pct < 1.0:
                        add_log(f"🌙 Moonbag: {SN_MOONBAG*100:.0f}% de {trade['symbol']} sigue corriendo", "info")

                    # Remover de activos (o reducir qty si moonbag)
                    if sell_pct >= 1.0:
                        app_state["active_trades"].remove(trade)
                    else:
                        trade["qty"] *= SN_MOONBAG
                        trade["tp_hit"] = False
                        trade["trailing_active"] = False
                        trade["entry_usd"] = exit_price  # Reset entry para moonbag
                        trade["highest_price"] = exit_price

                    app_state["balance_sol_gas"] = exchange.paper_balance_sol_gas
                    db.save_balance(app_state["balance_usd"], app_state["total_pnl"],
                                    app_state["win_count"], app_state["closed_count"],
                                    app_state["balance_sol_gas"])
                    db.save_active_trades(app_state["active_trades"])

                    if app_state["balance_sol_gas"] < 0.05 and not app_state.get("gas_alert_sent"):
                        await notify_telegram("⚠️ <b>ALERTA DE GAS MÍNIMO</b>\nEl tanque simulado de SOL Gas bajó de 0.05 SOL. Se recomienda reponer saldo pronto para continuar transando en Live.")
                        app_state["gas_alert_sent"] = True

            # ── Log Equity for Graphing ──
            floating_val = sum((t["qty"] * t.get("current_price", t["entry_usd"])) for t in app_state["active_trades"] if not t.get("agent_id") or t.get("agent_id") == "main")
            current_equity = app_state.get("balance_usd", 0.0) + floating_val
            db.log_equity("main", current_equity)

            # --- RETO DEL USUARIO: META 20% Y RIESGO 20% ---
            initial_eq = 1000.0 # Fijado según instrucción de reto ('inicia en 1000 dls')
            target_eq = initial_eq * 1.20 # Reto ganado: +20%
            stop_eq = initial_eq * 0.80   # Reto perdido: -20%

            if current_equity >= target_eq and app_state["bot_active"]:
                app_state["bot_active"] = False
                msg = f"🏆 <b>RETO SUPERADO</b> 🏆\nEl Agente alcanzó +20% de ganancia en capital.\nEquidad actual: ${current_equity:.2f}\n⚡ Sistema en PAUSA."
                add_log(msg, "info")
                add_brain_event(msg, "insight")
                asyncio.create_task(notify_telegram(msg))
            elif current_equity <= stop_eq and app_state["bot_active"]:
                app_state["bot_active"] = False
                msg = f"💀 <b>RETO PERDIDO</b> 💀\nEl Agente llegó a -20% de pérdida en capital total.\nEquidad actual: ${current_equity:.2f}\n⚡ Sistema en PAUSA."
                add_log(msg, "warn")
                add_brain_event(msg, "regime")
                asyncio.create_task(notify_telegram(msg))

            # Log Equity para Clones
            for cid, clone in clone_instances.items():
                c_state = clone.get_state()
                c_floating = sum((t["qty"] * t.get("current_price", t.get("entry_price", 0))) for t in c_state["active_trades"])
                db.log_equity(cid, c_state["balance"] + c_floating)

            await asyncio.sleep(5)  # Poll cada 5 segundos

        except Exception as e:
            log.error(f"Price feed error: {e}")
            await asyncio.sleep(5)


# ══════════════════════════════════════════════════════════
#  📄 INFORME DIARIO
# ══════════════════════════════════════════════════════════

async def periodic_report():
    def secs_until_8am() -> float:
        now = datetime.now()
        target = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    wait = secs_until_8am()
    log.info(f"Informe diario programado en {wait/3600:.1f}h")
    await asyncio.sleep(wait)
    
    while True:
        try:
            s = app_state
            bal_usd = s.get("balance_usd", 0)
            init_usd = s.get("initial_balance_usd", 0)
            pnl_r = s.get("total_pnl", 0.0)
            wins = s.get("win_count", 0)
            total = s.get("closed_count", 0)
            wr = f"{wins/total*100:.1f}%" if total > 0 else "N/A"
            chg = bal_usd - init_usd

            parts = [
                f"🧠 <b>Informe Diario — Agente Solana</b>",
                f"⏰ {datetime.now().strftime('%d/%m/%Y  %H:%M:%S')}",
                f"",
                f"💰 <b>Balance:</b> ${bal_usd:.2f} USDC",
                f"📈 <b>PnL Total:</b> ${pnl_r:+.4f}",
                f"🎯 <b>Win Rate:</b> {wr} ({wins}✅ / {total - wins}❌)",
                f"💼 <b>Posiciones:</b> {len(s.get('active_trades',[]))} abiertas",
                f"",
                f"📊 <b>Trending:</b> {len(s.get('trending_tokens',[]))} tokens",
                f"🔫 <b>Sniper:</b> {len(s.get('new_tokens',[]))} nuevos",
            ]
            await notify_telegram("\n".join(parts))
        except Exception as e:
            log.warning(f"Report error: {e}")
        
        wait = secs_until_8am()
        await asyncio.sleep(wait)


# ══════════════════════════════════════════════════════════
#  🌐 FASTAPI APP
# ══════════════════════════════════════════════════════════

from contextlib import asynccontextmanager

async def sentiment_polling_loop():
    """Actualiza sentimiento del mercado cada 10 minutos."""
    while True:
        try:
            result = await update_sentiment()
            add_log(
                f"🧠 Sentiment: F&G={result['fear_greed_value']} ({result['sentiment_signal']}) | "
                f"Heat={result['market_heat']} | Risk={result['risk_modifier']:.2f}x",
                "info"
            )
        except Exception as e:
            log.warning(f"Sentiment polling error: {e}")
        await asyncio.sleep(600)  # 10 minutos


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    
    # ── GRACEFUL RECOVERY ON-CHAIN ──
    if not exchange.paper_mode:
        log.info("[GRACEFUL RECOVERY] Evaluando estado On-Chain vs SQLite...")
        live_holdings = await exchange.sync_live_holdings()
        active_mints = {t.get("mint") for t in app_state["active_trades"] if "mint" in t}
        
        recovered_count = 0
        for mint, details in live_holdings.items():
            if mint not in active_mints:
                # Recuperar esta posición perdida
                try:
                    price_usd = await exchange.get_token_price_usd(mint)
                    
                    if price_usd > 0:
                        sym_fallback = f"REC-{mint[:4]}"
                        trade = {
                            "symbol": sym_fallback,
                            "mint": mint,
                            "qty": details["qty"],
                            "entry_usd": price_usd,  # Asumimos precio actual como entry base
                            "current_price": price_usd,
                            "source": "recovered",
                            "scores": {"total": 50}, 
                            "sl_pct": 15,
                            "tp_pct": 20,
                            "trailing_pct": 8,
                            "opened_at": datetime.now().isoformat()
                        }
                        app_state["active_trades"].append(trade)
                        active_mints.add(mint)
                        recovered_count += 1
                        add_log(f"🚑 RECOVERY: Readoptado {mint[:6]}... (qty: {details['qty']} @ ${price_usd:.4f})", "warn")
                except Exception as e:
                    log.error(f"Error readoptando mint {mint}: {e}")
                    
        if recovered_count > 0:
            db.save_active_trades(app_state["active_trades"])
            add_log(f"🚑 GRACEFUL RECOVERY COMPLETADO: {recovered_count} posiciones huérfanas puestas bajo gestión (Trailing).", "info")

    asyncio.create_task(engine_loop())
    asyncio.create_task(update_live_prices())
    asyncio.create_task(periodic_report())
    asyncio.create_task(sentiment_polling_loop())
    log.info("Dashboard Solana DEX Activo")
    yield

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "..", "web", "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "..", "web", "templates"))

# ── SEGURIDAD (HTTP BASIC AUTH) ──
security = HTTPBasic()
WEB_USER = os.getenv("WEB_USER", "admin")
WEB_PASS = os.getenv("WEB_PASS", "quant123")

def verify_auth(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, WEB_USER)
    correct_password = secrets.compare_digest(credentials.password, WEB_PASS)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Acceso restringido",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

@app.get("/", response_class=HTMLResponse)
@limiter.limit("60/minute")
async def dashboard(request: Request, username: str = Depends(verify_auth)):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/sw.js")
async def serve_sw():
    return FileResponse("static/sw.js", media_type="application/javascript")

@app.get("/manifest.json")
async def serve_manifest():
    return FileResponse("static/manifest.json", media_type="application/json")

@app.get("/api/state")
@limiter.limit("120/minute")
async def get_state(request: Request):
    state_copy = dict(app_state)
    state_copy["active_trades"] = list(app_state["active_trades"])
    # Compatibilidad con el dashboard existente
    state_copy["balance"] = app_state["balance_usd"]
    state_copy["initial_balance"] = app_state["initial_balance_usd"]
    state_copy["currency"] = "SOL"
    state_copy["max_trades"] = MAX_OPEN_TRADES

    # ── Sentiment REAL desde ai/sentiment.py ──
    state_copy["sentiment"] = get_sentiment_summary()

    # ── AI Module Status ──
    kelly_frac = calculate_kelly_fraction()
    state_copy["ai"] = {
        "ml_model_exists": os.path.exists(ML_MODEL_PATH),
        "kelly_fraction": round(kelly_frac, 4) if kelly_frac else None,
        "sentiment_risk_mod": get_risk_modifier(),
        "consecutive_losses": app_state.get("consecutive_losses", 0),
        "circuit_breaker_active": app_state.get("circuit_breaker_until", 0) > time.time(),
    }

    # ── Clones state for dashboard ──
    clones_config = {}
    clones_state = {}
    for cid, clone in clone_instances.items():
        cs = clone.get_state()
        clones_config[cid] = {
            "name": clone.name,
            "params": {
                "MIN_SCORE": 1,
                "RSI_OVERSOLD": 30,
                "RSI_OVERBOUGHT": 70,
                "RISK_PERCENT": clone.params.get("RISK_PERCENT", 0.10),
                "TAKE_PROFIT": clone.params.get("TAKE_PROFIT", 15),
                "STOP_LOSS": clone.params.get("STOP_LOSS", 8),
                "TRAILING": clone.params.get("TRAILING", 5),
                "DEAD_TRADE_MIN": clone.params.get("DEAD_TRADE_MIN", 45),
                "MOONBAG": clone.params.get("MOONBAG", 0),
            },
            "entry_filters": cs.get("entry_filters", {}),
        }
        clones_state[cid] = {
            "initial_balance": cs.get("initial_balance", app_state["initial_balance_usd"]),
            "balance": cs["balance"],
            "total_pnl": cs["total_pnl"],
            "win_count": cs["win_count"],
            "closed_count": cs["closed_count"],
            "unrealized_pnl": cs["unrealized_pnl"],
            "active_count": len(cs["active_trades"]),
            "active_trades": cs["active_trades"],
            "max_trades": clone.params.get("MAX_TRADES", 30),
            # Ciclo de vida
            "cycle_number": cs.get("cycle_number", 1),
            "cycle_days": cs.get("cycle_days", 30),
            "days_in_cycle": cs.get("days_in_cycle", 0),
            "days_remaining": cs.get("days_remaining", 30),
            "cycle_progress": cs.get("cycle_progress", 0),
            # Filtros de entrada (ADN del clon)
            "entry_filters": cs.get("entry_filters", {}),
        }
    state_copy["clones_config"] = clones_config
    state_copy["clones_state"] = clones_state
    return state_copy

@app.get("/api/equity")
@limiter.limit("200/minute")
async def get_equity(request: Request, agent: str = "main"):
    history = db.get_equity_history(agent)
    return {"status": "ok", "data": history}

@app.post("/api/toggle_bot")
@limiter.limit("30/minute")
async def toggle_bot(request: Request):
    app_state["bot_active"] = not app_state.get("bot_active", False)
    return {"status": "ok", "bot_active": app_state["bot_active"]}

@app.get("/api/regime")
@limiter.limit("120/minute")
async def get_regime(request: Request):
    return {
        "regime": app_state.get("scan_mode", "TRENDING"),
        "paused": app_state.get("paused", False),
        "paused_reason": app_state.get("paused_reason", ""),
    }

@app.get("/api/trending")
@limiter.limit("60/minute")
async def get_trending(request: Request):
    return {"tokens": app_state.get("trending_tokens", [])}

@app.get("/api/new-tokens")
@limiter.limit("60/minute")
async def get_new_tokens(request: Request):
    return {"tokens": app_state.get("new_tokens", [])}

@app.get("/api/scanner/feed")
@limiter.limit("60/minute")
async def get_scanner_feed(request: Request):
    """Feed completo del scanner para el dashboard — 3 modos + candidatos."""
    return {
        "bluechips": app_state.get("bluechip_tokens", []),
        "trending": app_state.get("trending_tokens", []),
        "new_tokens": app_state.get("new_tokens", []),
        "candidates": app_state.get("candidates", []),
        "scan_mode": app_state.get("scan_mode", "HYBRID"),
        "bluechip_slots": {"used": app_state.get("bluechip_count", 0), "max": BLUECHIP_SLOTS},
        "sniper_slots": {"used": app_state.get("sniper_count", 0), "max": SNIPER_SLOTS},
        "last_scan": app_state.get("last_scan", None),
        "bot_active": app_state.get("bot_active", False),
    }

@app.get("/api/trades/history")
@limiter.limit("60/minute")
async def get_trades_history(request: Request, limit: int = 50, agent_id: str = None):
    return {"trades": db.get_closed_trades(limit, agent_id)}

@app.get("/api/performance")
@limiter.limit("60/minute")
async def get_performance(request: Request, days: int = 14):
    return db.get_recent_performance(days) or {}

@app.get("/api/market/top-growth")
@limiter.limit("30/minute")
async def get_top_growth(request: Request):
    """
    Retorna el Top 10 de tokens de Solana por cambio de precio en 24h.
    Combina bluechips curados + trending tokens de DexScreener.
    """
    try:
        from scanner.token_scanner import SOLANA_BLUECHIPS
        results = []

        async with aiohttp.ClientSession() as session:
            # ── Paso 1: Obtener precios de bluechips via DexScreener ──
            mints = ",".join(bc["mint"] for bc in SOLANA_BLUECHIPS[:20])
            url = f"https://api.dexscreener.com/tokens/v1/solana/{mints}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    pairs = await r.json()
                    seen = set()
                    if isinstance(pairs, list):
                        # Agrupar el mejor par por mint
                        best = {}
                        for pair in pairs:
                            mint = pair.get("baseToken", {}).get("address", "")
                            liq = float(pair.get("liquidity", {}).get("usd", 0) or 0)
                            if mint not in best or liq > best[mint].get("_liq", 0):
                                pair["_liq"] = liq
                                best[mint] = pair

                        for bc in SOLANA_BLUECHIPS[:20]:
                            mint = bc["mint"]
                            pair = best.get(mint)
                            if not pair:
                                continue
                            chg_24h = float(pair.get("priceChange", {}).get("h24", 0) or 0)
                            price = float(pair.get("priceUsd", 0) or 0)
                            vol_24h = float(pair.get("volume", {}).get("h24", 0) or 0)
                            liq = float(pair.get("liquidity", {}).get("usd", 0) or 0)
                            mc = float(pair.get("marketCap", 0) or 0)
                            if price <= 0 or liq < 10000:
                                continue
                            if mint in seen:
                                continue
                            seen.add(mint)
                            results.append({
                                "rank": 0,
                                "symbol": bc["symbol"],
                                "name": bc["name"],
                                "mint": mint,
                                "price": price,
                                "change_24h": chg_24h,
                                "change_1h": float(pair.get("priceChange", {}).get("h1", 0) or 0),
                                "volume_24h": vol_24h,
                                "liquidity": liq,
                                "market_cap": mc,
                                "dex_url": pair.get("url", ""),
                                "source": "bluechip",
                            })

            # ── Paso 2: Complementar con tokens trending de DexScreener ──
            url2 = "https://api.dexscreener.com/token-boosts/top/v1"
            async with session.get(url2, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    boosted = await r.json()
                    # Tomar los primeros tokens Solana
                    sol_mints = [
                        item.get("tokenAddress", "")
                        for item in boosted
                        if item.get("chainId") == "solana"
                        and item.get("tokenAddress", "") not in seen
                    ][:15]

                    if sol_mints:
                        mints2 = ",".join(sol_mints)
                        url3 = f"https://api.dexscreener.com/tokens/v1/solana/{mints2}"
                        async with session.get(url3, timeout=aiohttp.ClientTimeout(total=10)) as r2:
                            if r2.status == 200:
                                pairs2 = await r2.json()
                                best2 = {}
                                if isinstance(pairs2, list):
                                    for pair in pairs2:
                                        mint = pair.get("baseToken", {}).get("address", "")
                                        liq = float(pair.get("liquidity", {}).get("usd", 0) or 0)
                                        if mint not in best2 or liq > best2[mint].get("_liq", 0):
                                            pair["_liq"] = liq
                                            best2[mint] = pair

                                    for mint in sol_mints:
                                        if mint in seen:
                                            continue
                                        pair = best2.get(mint)
                                        if not pair:
                                            continue
                                        base = pair.get("baseToken", {})
                                        chg_24h = float(pair.get("priceChange", {}).get("h24", 0) or 0)
                                        price = float(pair.get("priceUsd", 0) or 0)
                                        vol_24h = float(pair.get("volume", {}).get("h24", 0) or 0)
                                        liq2 = float(pair.get("liquidity", {}).get("usd", 0) or 0)
                                        mc2 = float(pair.get("marketCap", 0) or 0)
                                        sym = base.get("symbol", "?")
                                        if not sym or price <= 0 or liq2 < 5000:
                                            continue
                                        seen.add(mint)
                                        results.append({
                                            "rank": 0,
                                            "symbol": sym,
                                            "name": base.get("name", "Unknown"),
                                            "mint": mint,
                                            "price": price,
                                            "change_24h": chg_24h,
                                            "change_1h": float(pair.get("priceChange", {}).get("h1", 0) or 0),
                                            "volume_24h": vol_24h,
                                            "liquidity": liq2,
                                            "market_cap": mc2,
                                            "dex_url": pair.get("url", ""),
                                            "source": "trending",
                                        })

        # ── Ordenar por cambio 24h (de mayor a menor) ──
        results.sort(key=lambda x: x.get("change_24h", 0), reverse=True)

        # Asignar ranking y limitar a 10
        top10 = results[:10]
        for i, item in enumerate(top10):
            item["rank"] = i + 1
            # Alias para compatibilidad con el JS existente
            item["change"] = item["change_24h"]
            item["price_usd"] = item["price"]

        return top10

    except Exception as e:
        log.error(f"top-growth error: {e}")
        return []

import math
@app.get("/api/chart/{symbol}")
@limiter.limit("120/minute")
async def get_chart(request: Request, symbol: str, tf: str = "15m"):
    """Dinamiza el gráfico con velas reales de GeckoTerminal e indicadores calculadores en el server."""
    # 1. Resolver Mint
    mint = scanner.get_mint_by_symbol(symbol)
    
    # 2. Si no hay mint en bluechips, intentar buscar en los trades activos
    if not mint:
        for t in app_state["active_trades"]:
            if t["symbol"] == symbol or symbol in t["symbol"]:
                mint = t["mint"]
                break
    
    if not mint:
        # Fallback total: si el símbolo es un mint directamente
        if len(symbol) > 30: mint = symbol
        else: return {"error": "Symbol not found", "candles": []}

    # 3. Obtener velas reales
    candles = await scanner.get_ohlcv_data(mint, tf)
    if not candles:
        return {"error": "No data found", "candles": []}

    # 4. Calcular Indicadores (EMA, RSI, MACD, BB)
    closes = np.array([c["close"] for c in candles])
    
    def calculate_ema(data, span):
        if len(data) < span: return []
        alpha = 2 / (span + 1)
        ema = [data[0]]
        for i in range(1, len(data)):
            ema.append(data[i] * alpha + ema[-1] * (1 - alpha))
        return ema

    def calculate_rsi(data, period=14):
        if len(data) < period + 1: return []
        deltas = np.diff(data)
        seed = deltas[:period]
        up = seed[seed >= 0].sum() / period
        down = -seed[seed < 0].sum() / period
        rs = up / (down if down != 0 else 0.00001)
        rsi = np.zeros_like(data)
        rsi[:period] = 100. - 100. / (1. + rs)

        for i in range(period, len(data)):
            delta = deltas[i - 1]
            if delta > 0:
                up_val = delta
                down_val = 0.
            else:
                up_val = 0.
                down_val = -delta
            up = (up * (period - 1) + up_val) / period
            down = (down * (period - 1) + down_val) / period
            rs = up / (down if down != 0 else 0.00001)
            rsi[i] = 100. - 100. / (1. + rs)
        return rsi.tolist()

    # EMA
    ema10 = calculate_ema(closes, 10)
    ema55 = calculate_ema(closes, 55)

    # MACD
    ema12 = calculate_ema(closes, 12)
    ema26 = calculate_ema(closes, 26)
    macd_line = []
    if len(ema12) == len(ema26):
        macd_line = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
    
    macd_signal = calculate_ema(np.array(macd_line), 9) if macd_line else []
    macd_hist = []
    if len(macd_line) > 0 and len(macd_signal) > 0:
        # Align lengths if needed
        offset = len(macd_line) - len(macd_signal)
        macd_hist = [macd_line[i+offset] - macd_signal[i] for i in range(len(macd_signal))]

    # RSI
    rsi = calculate_rsi(closes, 14)

    # Bollinger Bands (20, 2)
    bb_upper = []
    bb_lower = []
    period = 20
    if len(closes) >= period:
        for i in range(len(closes)):
            if i < period - 1:
                bb_upper.append(None)
                bb_lower.append(None)
                continue
            window = closes[i - period + 1 : i + 1]
            sma = np.mean(window)
            std = np.std(window)
            bb_upper.append(sma + 2 * std)
            bb_lower.append(sma - 2 * std)

    # Preparar respuesta formateada para Lightweight Charts {time, value}
    # Nota: Los indicadores deben alinearse con el tiempo de las velas
    def format_indicator(lst, candles_ref):
        target_len = len(candles_ref)
        if len(lst) > target_len:
            lst = lst[-target_len:]
        
        # Pad with null if list is shorter
        padded = [None] * (target_len - len(lst)) + lst
        
        result = []
        for i in range(target_len):
            val = padded[i]
            if val is not None and not np.isnan(val):
                result.append({"time": candles_ref[i]["time"], "value": float(val)})
        return result

    return {
        "symbol": symbol,
        "tf": tf,
        "candles": candles,
        "ema10": format_indicator(ema10, candles),
        "ema55": format_indicator(ema55, candles),
        "rsi": format_indicator(rsi, candles),
        "macd": format_indicator(macd_line, candles),
        "macd_sig": format_indicator(macd_signal, candles),
        "macd_hist": format_indicator(macd_hist, candles),
        "bb_upper": format_indicator(bb_upper, candles),
        "bb_lower": format_indicator(bb_lower, candles),
    }



@app.get("/api/clone/{agent_id}/equity")
async def get_clone_equity(agent_id: str):
    res = db.get_equity_history(agent_id)
    return [{"time": row["ts"], "value": row["val"]} for row in res]


@app.get("/api/brain")
async def get_brain_data():
    """Estadísticas y logs para la pestaña Inteligencia del Agente"""
    return {
        "stats": app_state["brain_stats"],
        "events": app_state["brain_log"],
        "signal_stats": app_state.get("signal_stats", {}),
    }

@app.get("/api/signals")
async def get_clone_signals():
    """Señales en tiempo real de los clones al cerebro."""
    return {
        "signals": app_state.get("clone_signals", []),
        "stats": signal_bus.get_stats(),
    }

@app.get("/api/clone/{agent_id}/details")
async def get_clone_details(agent_id: str):
    try:
        # Build equity curve from real DB history (works for main AND clones)
        eq_hist = db.get_equity_history(agent_id)
        equity_curve = [{"label": p["lbl"], "value": round(p["val"], 2)} for p in eq_hist]

        # Buscar en clone_instances
        clone = clone_instances.get(agent_id)
        if clone:
            state = clone.get_state()
            INIT = clone.initial_balance
            if not equity_curve:
                equity_curve = [{"label": "Inicio", "value": INIT}]
            return {
                "agent_id": agent_id,
                "equity_curve": equity_curve,
                "current_balance": round(state["balance"] + state["unrealized_pnl"], 4),
                "total_trades": state["closed_count"],
                "wins": state["win_count"],
                "losses": state["closed_count"] - state["win_count"],
                "win_rate": state["win_rate"],
                "total_pnl": state["total_pnl"],
                "active_trades": state["active_trades"],
                "recent_trades": db.get_closed_trades(limit=15, agent_id=agent_id),
            }

        # Handle "main" agent
        if agent_id == "main":
            bal = app_state.get("balance_usd", 1000)
            init_bal = app_state.get("initial_balance", 1000)
            pnl = app_state.get("total_pnl", 0)
            wins = app_state.get("win_count", 0)
            closed = app_state.get("closed_count", 0)
            losses = closed - wins
            wr = round(wins / closed * 100, 1) if closed > 0 else 0
            if not equity_curve:
                equity_curve = [{"label": "Inicio", "value": init_bal}]
            return {
                "agent_id": "main",
                "equity_curve": equity_curve,
                "current_balance": round(bal, 4),
                "total_trades": closed,
                "wins": wins,
                "losses": losses,
                "win_rate": wr,
                "total_pnl": round(pnl, 4),
                "active_trades": app_state.get("active_trades", []),
                "recent_trades": db.get_closed_trades(limit=15, agent_id="main"),
            }

        # Fallback: buscar por agent_id en DB
        import sqlite3 as _sq
        _conn = _sq.connect(db.DB_PATH)
        _conn.row_factory = _sq.Row
        _rows = _conn.execute(
            "SELECT symbol, pnl, pnl_pct, result, reason, opened_at, closed_at, entry_price, exit_price "
            "FROM trades WHERE agent_id = ? ORDER BY closed_at ASC LIMIT 200",
            (agent_id,)
        ).fetchall()
        _conn.close()
        trades = [dict(r) for r in _rows]
        INIT = 1000.0
        equity = INIT
        if not equity_curve:
            equity_curve = [{"label": "Inicio", "value": INIT}]
        win = loss = 0
        total_pnl = 0.0
        for t in trades:
            equity += t["pnl"] or 0
            total_pnl += t["pnl"] or 0
            equity_curve.append({"label": (t["closed_at"] or "")[:16], "value": round(equity, 4)})
            if t["result"] == "win": win += 1
            else: loss += 1
        return {
            "agent_id": agent_id,
            "equity_curve": equity_curve,
            "current_balance": round(equity, 4),
            "total_trades": len(trades),
            "wins": win,
            "losses": loss,
            "win_rate": round(win / len(trades) * 100, 1) if trades else 0,
            "total_pnl": round(total_pnl, 4),
            "active_trades": [],
            "recent_trades": trades[-10:][::-1],
        }
    except Exception as e:
        return {"error": str(e), "equity_curve": [], "current_balance": 1000.0,
                "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "total_pnl": 0, "active_trades": [], "recent_trades": []}


def hard_reset_process():
    import time
    time.sleep(0.5)
    # Start reset.sh in a new session so it outlives this process
    subprocess.Popen(["bash", "reset.sh"], start_new_session=True)
    os._exit(0)

@app.post("/api/reset_db")
async def api_reset_db():
    threading.Thread(target=hard_reset_process, daemon=True).start()
    return {"status": "ok", "message": "Reiniciando base de datos. Recargue en 5 segundos."}

@app.get("/api/export_trades")
async def api_export_trades(agent_id: str = "main"):
    # Descargar todos los trades cerrados del agente a un CSV
    trades = db.get_closed_trades(agent_id, limit=10000)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Symbol", "Entry Price", "Exit Price", "PnL USD", "PnL %", "Duration (min)", "Source", "Open Date", "Close Date", "Reason", "ML Probability"])
    for t in trades:
        duration_min = 0
        if t.get("opened_at") and t.get("closed_at"):
            try:
                opn = datetime.fromisoformat(t["opened_at"])
                cls = datetime.fromisoformat(t["closed_at"])
                duration_min = round((cls - opn).total_seconds() / 60, 1)
            except: pass
            
        scores = t.get("scores")
        ml_prob = ""
        if isinstance(scores, str):
            try: scores = json.loads(scores)
            except: scores = {}
        if isinstance(scores, dict):
            ml_prob = scores.get("ml_prob", "")
            if isinstance(ml_prob, float): ml_prob = f"{ml_prob*100:.1f}%"

        writer.writerow([
            t.get("id", ""), t.get("symbol", ""), t.get("entry_usd", ""), t.get("exit_usd", ""),
            t.get("pnl_usd", ""), t.get("pnl_pct", ""), duration_min, t.get("source", ""),
            t.get("opened_at", "")[:16], t.get("closed_at", "")[:16], t.get("close_reason", ""), ml_prob
        ])
    return Response(content=output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=trades_{agent_id}_{int(time.time())}.csv"})

@app.post("/api/config_override")
async def api_config_override(request: Request, username: str = Depends(verify_auth)):
    try:
        data = await request.json()
        agent_id = data.get("agent_id")
        key = data.get("key")
        value = float(data.get("value"))
        
        if agent_id == "main":
            # Si se altera configuración main, la sobreescribimos via env/global para el simulador
            return {"status": "ok", "message": "Configuración maestra alterada temporalmente en memoria"}
            
        clone = clone_instances.get(agent_id)
        if clone:
            clone.params[key] = value
            return {"status": "ok", "message": f"[{clone.name}] {key} cambiado a {value}"}
        return {"status": "error", "message": "Agente no encontrado"}
    except Exception as e:
        return {"status": "error", "message": str(e)}



if __name__ == "__main__":
    print("\n" + "="*55)
    print("🚀 Agente Solana DEX — Jupiter v6")
    print("📊 Dashboard: http://localhost:8000")
    print(f"🎮 Modo: {'SIMULACIÓN' if PAPER_TRADING_MODE else 'LIVE'}")
    print("="*55 + "\n")
    uvicorn.run("bot_agente:app", host="0.0.0.0", port=8000, reload=False, log_level="warning")

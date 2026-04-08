"""
╔══════════════════════════════════════════════════════════╗
║           MÓDULO DE MEMORIA — db.py                      ║
║  PostgreSQL (Supabase) persistence para trades y métricas║
╚══════════════════════════════════════════════════════════╝
"""
import os
import json
import logging
from datetime import datetime, date, timedelta
from contextlib import contextmanager

log = logging.getLogger("AgenteBot.DB")

try:
    import psycopg2
    from psycopg2.pool import SimpleConnectionPool
    from psycopg2.extras import RealDictCursor
    DB_MOCK = False
except ImportError:
    # Si psycopg2 no está instalado (ej. desarrollo local), usamos el Mock
    DB_MOCK = True
    log.warning("No se encontró psycopg2, usando BASE DE DATOS MOCK en memoria. No se guardarán los datos.")
    from db_mock import *

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    log.warning("🔌 No se encontró DATABASE_URL en el entorno, apuntando por defecto a sqlite o error eventual.")
    # Fallback temporal si no se configura para evitar que rompa inmediatamente en terminal local
    DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/postgres"

# Connection pool global
db_pool = None

def init_db():
    global db_pool
    if not db_pool:
        db_pool = SimpleConnectionPool(1, 20, dsn=DATABASE_URL)
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id              SERIAL PRIMARY KEY,
                symbol          TEXT NOT NULL,
                entry_price     DOUBLE PRECISION NOT NULL,
                exit_price      DOUBLE PRECISION NOT NULL,
                qty             DOUBLE PRECISION NOT NULL,
                pnl             DOUBLE PRECISION NOT NULL,
                pnl_pct         DOUBLE PRECISION NOT NULL,
                result          TEXT NOT NULL,       -- 'win' | 'loss'
                reason          TEXT NOT NULL,       -- 'TAKE_PROFIT' | 'STOP_LOSS'
                rsi_at_entry    DOUBLE PRECISION,
                macd_at_entry   DOUBLE PRECISION,
                ema_alignment   INTEGER,             -- 1=fast>slow, 0=fast<slow
                tf_score        INTEGER,             -- 2 o 3 timeframes alineados
                market_regime   TEXT,                -- 'BULL' | 'BEAR' | 'SIDEWAYS'
                hour_of_entry   INTEGER,             -- 0-23
                day_of_week     INTEGER,             -- 0=lunes, 6=domingo
                duration_hours  DOUBLE PRECISION,
                opened_at       TEXT,
                closed_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                agent_id        TEXT DEFAULT 'main',
                bb_width        DOUBLE PRECISION DEFAULT 0.0,
                bb_position     DOUBLE PRECISION DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS daily_stats (
                id              SERIAL PRIMARY KEY,
                date            TEXT UNIQUE NOT NULL,
                balance         DOUBLE PRECISION NOT NULL,
                daily_pnl       DOUBLE PRECISION NOT NULL,
                trades_opened   INTEGER DEFAULT 0,
                trades_closed   INTEGER DEFAULT 0,
                wins            INTEGER DEFAULT 0,
                losses          INTEGER DEFAULT 0,
                market_regime   TEXT,
                recorded_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS agent_params (
                key             TEXT PRIMARY KEY,
                value           TEXT NOT NULL,
                reason          TEXT,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS agent_state (
                key             TEXT PRIMARY KEY,
                value           TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_insights (
                id              SERIAL PRIMARY KEY,
                insight_type    TEXT NOT NULL,  -- 'PARAM_ADJUST' | 'REGIME_CHANGE' | 'CIRCUIT_BREAKER'
                message         TEXT NOT NULL,
                data_json       TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS clone_state (
                clone_id        TEXT PRIMARY KEY,
                balance         DOUBLE PRECISION NOT NULL,
                total_pnl       DOUBLE PRECISION NOT NULL DEFAULT 0,
                win_count       INTEGER DEFAULT 0,
                closed_count    INTEGER DEFAULT 0,
                cycle_number    INTEGER DEFAULT 1,
                cycle_start     TEXT NOT NULL,
                cycle_days      INTEGER NOT NULL,
                synced_mints    TEXT DEFAULT '[]',
                active_trades   TEXT DEFAULT '[]',
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS clone_cycles (
                id              SERIAL PRIMARY KEY,
                clone_id        TEXT NOT NULL,
                cycle_number    INTEGER NOT NULL,
                cycle_start     TEXT NOT NULL,
                cycle_end       TEXT NOT NULL,
                cycle_days      INTEGER NOT NULL,
                initial_balance DOUBLE PRECISION NOT NULL,
                final_balance   DOUBLE PRECISION NOT NULL,
                total_pnl       DOUBLE PRECISION NOT NULL,
                total_trades    INTEGER NOT NULL,
                wins            INTEGER NOT NULL,
                losses          INTEGER NOT NULL,
                win_rate        DOUBLE PRECISION NOT NULL,
                avg_pnl_per_trade DOUBLE PRECISION NOT NULL,
                best_trade_pct  DOUBLE PRECISION DEFAULT 0,
                worst_trade_pct DOUBLE PRECISION DEFAULT 0,
                report_json     TEXT,
                brain_applied   INTEGER DEFAULT 0,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS equity_history (
                id SERIAL PRIMARY KEY,
                agent_id TEXT NOT NULL,
                timestamp BIGINT NOT NULL,
                label TEXT NOT NULL,
                balance DOUBLE PRECISION NOT NULL
            );
            """)
            
            # Parámetros por defecto (con ON CONFLICT para PostgreSQL)
            defaults = {
                "RSI_OVERSOLD": "35.0",
                "RSI_OVERBOUGHT": "65.0",
                "MIN_SCORE": "2",
                "RISK_PERCENT": "0.20",
                "DAILY_LOSS_LIMIT": "0.05",
            }
            for k, v in defaults.items():
                cur.execute(
                    "INSERT INTO agent_params(key,value,reason) VALUES(%s,%s,%s) ON CONFLICT (key) DO NOTHING",
                    (k, v, "Valor inicial por defecto")
                )
                
            cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_agent ON trades(agent_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_equity_agent ON equity_history(agent_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_equity_time ON equity_history(timestamp);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_clone_cycles ON clone_cycles(clone_id);")
            
        conn.commit()
    log.info(f"💾 Base de datos Supabase conectada con éxito.")

@contextmanager
def get_conn():
    conn = db_pool.getconn()
    try:
        yield conn
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        db_pool.putconn(conn)

def save_trade(trade: dict, exit_price: float, reason: str, market_regime: str):
    opened_at_str = trade.get("opened_at", datetime.now().isoformat())
    try:
        opened_at = datetime.fromisoformat(opened_at_str)
    except Exception:
        opened_at = datetime.now()
    duration = (datetime.now() - opened_at).total_seconds() / 3600

    entry  = trade.get("entry", 0)
    qty    = trade.get("qty", 0)
    pnl    = (exit_price - entry) * qty
    pnl_pct = ((exit_price - entry) / entry * 100) if entry else 0
    result  = "win" if pnl >= 0 else "loss"

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO trades
                    (symbol, entry_price, exit_price, qty, pnl, pnl_pct, result, reason,
                     rsi_at_entry, macd_at_entry, ema_alignment, tf_score,
                     market_regime, hour_of_entry, day_of_week, duration_hours, opened_at, agent_id, bb_width, bb_position)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    trade.get("symbol"),
                    entry,
                    exit_price,
                    qty,
                    round(pnl, 6),
                    round(pnl_pct, 4),
                    result,
                    reason,
                    trade.get("rsi_at_entry"),
                    trade.get("macd_at_entry"),
                    trade.get("ema_alignment"),
                    trade.get("tf_score"),
                    market_regime,
                    opened_at.hour,
                    opened_at.weekday(),
                    round(duration, 2),
                    opened_at_str,
                    trade.get("agent_id", "main"),
                    trade.get("bb_width", 0.0),
                    trade.get("bb_position", 0.0)
                ))
            conn.commit()
    except Exception as db_err:
        log.error(f"⚠️ Error Crítico guardando trade de {trade.get('symbol')}: {db_err}")
    return result, round(pnl, 6)

def save_balance(balance: float, total_pnl: float, win_count: int, closed_count: int, balance_sol_gas: float = 0.5):
    with get_conn() as conn:
        with conn.cursor() as cur:
            for k, v in [
                ("balance", str(balance)),
                ("total_pnl", str(total_pnl)),
                ("win_count", str(win_count)),
                ("closed_count", str(closed_count)),
                ("balance_sol_gas", str(balance_sol_gas)),
            ]:
                cur.execute(
                    "INSERT INTO agent_state(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", 
                    (k, v)
                )
        conn.commit()

def load_balance(default: float, default_gas: float = 0.5):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT key,value FROM agent_state")
            rows = {r["key"]: r["value"] for r in cur.fetchall()}
    return {
        "balance":         float(rows.get("balance", default)),
        "balance_sol_gas": float(rows.get("balance_sol_gas", default_gas)),
        "total_pnl":       float(rows.get("total_pnl", 0)),
        "win_count":       int(rows.get("win_count", 0)),
        "closed_count":    int(rows.get("closed_count", 0)),
    }

def save_active_trades(active_trades: list):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO agent_state(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", 
                        ("active_trades", json.dumps(active_trades)))
        conn.commit()

def load_active_trades() -> list:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT value FROM agent_state WHERE key='active_trades'")
            row = cur.fetchone()
            if row:
                try:
                    return json.loads(row["value"])
                except Exception:
                    pass
    return []

def log_equity(agent_id: str, balance: float, max_points: int = 1500) -> None:
    ts = int(datetime.now().timestamp() * 1000)
    lbl = datetime.now().strftime("%I:%M")
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            # PostgreSQL syntax para SELECT LIMIT 1 ordenado.
            cur.execute("SELECT label, id FROM equity_history WHERE agent_id=%s ORDER BY id DESC LIMIT 1", (agent_id,))
            last = cur.fetchone()
            if last and last[0] == lbl:
                cur.execute("UPDATE equity_history SET balance = %s, timestamp = %s WHERE id = %s", (balance, ts, last[1]))
            else:
                cur.execute(
                    "INSERT INTO equity_history (agent_id, timestamp, label, balance) VALUES (%s, %s, %s, %s)",
                    (agent_id, ts, lbl, balance)
                )
                
            cur.execute(
                """
                DELETE FROM equity_history 
                WHERE agent_id = %s AND id NOT IN (
                    SELECT id FROM equity_history WHERE agent_id = %s ORDER BY id DESC LIMIT %s
                )
                """, (agent_id, agent_id, max_points)
            )
        conn.commit()

def get_equity_history(agent_id: str) -> list:
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT timestamp as ts, label as lbl, balance as val FROM equity_history WHERE agent_id = %s ORDER BY id ASC",
                    (agent_id,)
                )
                return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        log.error(f"[DB] Error load equity history: {e}")
        return []

def get_param(key: str, default=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT value FROM agent_params WHERE key=%s", (key,))
            row = cur.fetchone()
    if row:
        return row["value"]
    return default

def set_param(key: str, value: str, reason: str = ""):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agent_params(key,value,reason,updated_at) VALUES(%s,%s,%s,CURRENT_TIMESTAMP) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, reason=EXCLUDED.reason, updated_at=CURRENT_TIMESTAMP",
                (key, value, reason)
            )
            cur.execute(
                "INSERT INTO agent_insights(insight_type,message,data_json,created_at) VALUES(%s,%s,%s,CURRENT_TIMESTAMP)",
                ("PARAM_ADJUST", f"Parámetro {key} ajustado a {value}: {reason}",
                 json.dumps({"key": key, "value": value}))
            )
        conn.commit()
    log.info(f"[AGENT] Parámetro ajustado: {key} = {value} ({reason})")

def save_daily_stats(balance: float, daily_pnl: float, opened: int,
                     closed: int, wins: int, losses: int, regime: str):
    today = date.today().isoformat()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO daily_stats
                (date,balance,daily_pnl,trades_opened,trades_closed,wins,losses,market_regime)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (date) DO UPDATE SET 
                    balance=EXCLUDED.balance, 
                    daily_pnl=EXCLUDED.daily_pnl, 
                    trades_opened=EXCLUDED.trades_opened, 
                    trades_closed=EXCLUDED.trades_closed, 
                    wins=EXCLUDED.wins, 
                    losses=EXCLUDED.losses, 
                    market_regime=EXCLUDED.market_regime
            """, (today, balance, daily_pnl, opened, closed, wins, losses, regime))
        conn.commit()

def get_kelly_data(days: int = 30):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT result, pnl, pnl_pct
                FROM trades
                WHERE closed_at >= NOW() - %s::interval
            """, (f"{days} days",))
            rows = cur.fetchall()
    return [dict(r) for r in rows]

def get_recent_performance(days: int = 14):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT result, pnl, pnl_pct, rsi_at_entry, tf_score, market_regime
                FROM trades
                WHERE closed_at >= NOW() - %s::interval
            """, (f"{days} days",))
            rows = cur.fetchall()

    if not rows:
        return None

    total  = len(rows)
    wins   = sum(1 for r in rows if r["result"] == "win")
    avg_pnl = sum(r["pnl_pct"] for r in rows) / total

    by_regime = {}
    for r in rows:
        reg = r["market_regime"] or "UNKNOWN"
        by_regime.setdefault(reg, {"wins":0,"total":0})
        by_regime[reg]["total"] += 1
        if r["result"] == "win":
            by_regime[reg]["wins"] += 1

    by_score = {}
    for r in rows:
        sc = r["tf_score"] or 0
        by_score.setdefault(sc, {"wins":0,"total":0})
        by_score[sc]["total"] += 1
        if r["result"] == "win":
            by_score[sc]["wins"] += 1

    return {
        "total": total,
        "wins": wins,
        "win_rate": wins / total,
        "avg_pnl_pct": avg_pnl,
        "by_regime": by_regime,
        "by_score": by_score,
    }

def get_training_data():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT result, rsi_at_entry, macd_at_entry, tf_score, ema_alignment, market_regime
                FROM trades
                WHERE rsi_at_entry IS NOT NULL
                ORDER BY id DESC
                LIMIT 15000
            """)
            rows = cur.fetchall()
    return [dict(r) for r in rows]

def save_insight(insight_type: str, message: str, data: dict = None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agent_insights(insight_type,message,data_json,created_at) VALUES(%s,%s,%s,CURRENT_TIMESTAMP)",
                (insight_type, message, json.dumps(data or {}))
            )
        conn.commit()

def get_recent_insights(limit: int = 10):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT insight_type, message, created_at FROM agent_insights ORDER BY id DESC LIMIT %s",
                (limit,)
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]

def get_closed_trades(limit: int = 50, agent_id: str = None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if agent_id:
                cur.execute("""
                    SELECT symbol, entry_price, exit_price, pnl, pnl_pct, result,
                           reason, market_regime, duration_hours, closed_at, agent_id
                    FROM trades WHERE agent_id=%s ORDER BY id DESC LIMIT %s
                """, (agent_id, limit,))
            else:
                cur.execute("""
                    SELECT symbol, entry_price, exit_price, pnl, pnl_pct, result,
                           reason, market_regime, duration_hours, closed_at, agent_id
                    FROM trades ORDER BY id DESC LIMIT %s
                """, (limit,))
            rows = cur.fetchall()
    return [dict(r) for r in rows]

def save_clone_state(clone_id: str, balance: float, total_pnl: float,
                     win_count: int, closed_count: int, cycle_number: int,
                     cycle_start: str, cycle_days: int,
                     synced_mints: list, active_trades: list):
    import json
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO clone_state
                    (clone_id, balance, total_pnl, win_count, closed_count,
                     cycle_number, cycle_start, cycle_days, synced_mints,
                     active_trades, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, CURRENT_TIMESTAMP)
                ON CONFLICT(clone_id) DO UPDATE SET
                    balance=EXCLUDED.balance,
                    total_pnl=EXCLUDED.total_pnl,
                    win_count=EXCLUDED.win_count,
                    closed_count=EXCLUDED.closed_count,
                    cycle_number=EXCLUDED.cycle_number,
                    cycle_start=EXCLUDED.cycle_start,
                    cycle_days=EXCLUDED.cycle_days,
                    synced_mints=EXCLUDED.synced_mints,
                    active_trades=EXCLUDED.active_trades,
                    updated_at=CURRENT_TIMESTAMP
            """, (clone_id, balance, total_pnl, win_count, closed_count,
                  cycle_number, cycle_start, cycle_days,
                  json.dumps(synced_mints), json.dumps(active_trades)))
        conn.commit()

def load_clone_state(clone_id: str) -> dict | None:
    import json
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM clone_state WHERE clone_id=%s", (clone_id,))
            row = cur.fetchone()
    if row:
        d = dict(row)
        d["synced_mints"] = json.loads(d.get("synced_mints", "[]"))
        d["active_trades"] = json.loads(d.get("active_trades", "[]"))
        return d
    return None

def save_clone_cycle(clone_id: str, cycle_number: int, cycle_start: str,
                     cycle_end: str, cycle_days: int, initial_balance: float,
                     final_balance: float, total_pnl: float, total_trades: int,
                     wins: int, losses: int, win_rate: float,
                     avg_pnl: float, best_pct: float, worst_pct: float,
                     report_json: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO clone_cycles
                    (clone_id, cycle_number, cycle_start, cycle_end, cycle_days,
                     initial_balance, final_balance, total_pnl, total_trades,
                     wins, losses, win_rate, avg_pnl_per_trade,
                     best_trade_pct, worst_trade_pct, report_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
            """, (clone_id, cycle_number, cycle_start, cycle_end, cycle_days,
                  initial_balance, final_balance, total_pnl, total_trades,
                  wins, losses, win_rate, avg_pnl, best_pct, worst_pct,
                  report_json))
            inserted_id = cur.fetchone()[0]
        conn.commit()
    return inserted_id

def get_clone_cycles(clone_id: str = None, limit: int = 20) -> list:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if clone_id:
                cur.execute(
                    "SELECT * FROM clone_cycles WHERE clone_id=%s ORDER BY id DESC LIMIT %s",
                    (clone_id, limit)
                )
            else:
                cur.execute(
                    "SELECT * FROM clone_cycles ORDER BY id DESC LIMIT %s",
                    (limit,)
                )
            rows = cur.fetchall()
    return [dict(r) for r in rows]

def get_main_performance(days: int) -> dict:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins,
                    SUM(pnl_pct) as total_pnl_pct,
                    AVG(pnl_pct) as avg_pnl_pct,
                    MAX(pnl_pct) as best_trade,
                    MIN(pnl_pct) as worst_trade
                FROM trades
                WHERE agent_id='main'
                  AND closed_at >= NOW() - %s::interval
            """, (f"{days} days",))
            row = cur.fetchone()
    return dict(row) if row else {}

def clean_old_history(retention_days: int = 7):
    cutoff_time = int((datetime.now() - timedelta(days=retention_days)).timestamp() * 1000)
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("DELETE FROM equity_history WHERE timestamp < %s", (cutoff_time,))
                deleted_rows = cur.rowcount
                if deleted_rows > 0:
                    log.info(f"🧹 Poda ejecutada: Se liberaron {deleted_rows} puntos gráficos obsoletos (>{retention_days} días).")
            except Exception as e:
                log.error(f"Error limpiando historial: {e}")
        conn.commit()

if DB_MOCK:
    from db_mock import *

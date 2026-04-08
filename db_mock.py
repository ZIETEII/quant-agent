import logging
from datetime import datetime

log = logging.getLogger("AgenteBot.DB")

class MockCursor:
    def __init__(self):
        self.rows = []
    def execute(self, query, params=None):
        pass
    def fetchall(self):
        return self.rows
    def fetchone(self):
        return None
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

class MockConnection:
    def cursor(self, cursor_factory=None):
        return MockCursor()
    def commit(self):
        pass
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

class MockPool:
    def getconn(self):
        return MockConnection()
    def putconn(self, conn):
        pass

db_pool = MockPool()

def init_db(): log.info("Using MOCK DB initialized")
def get_conn(): return MockConnection()
def save_trade(*args, **kwargs): pass
def load_all_trades(*args, **kwargs): return []
def load_win_rate(*args): return 0.0
def get_daily_loss(*args, **kwargs): return 0.0
def record_daily_stats(*args, **kwargs): pass
def save_active_trades(*args, **kwargs): pass
def load_active_trades(): return {}
def save_balance(*args, **kwargs): pass
def load_balance(default, default_gas=0.5): 
    return {"balance": default, "balance_sol_gas": default_gas, "total_pnl": 0.0, "win_count": 0, "closed_count": 0}
def record_equity(*args, **kwargs): pass
def get_equity_history(*args, **kwargs): return []
def save_agent_param(*args, **kwargs): pass
def load_agent_param(key, default=None): return default
def save_agent_insight(*args, **kwargs): pass
def load_agent_insights(*args, **kwargs): return []
def load_recent_trades(*args, **kwargs): return []
def get_paginated_trades(*args, **kwargs): return []
def init_clone(*args, **kwargs): pass
def save_clone_cycle(*args, **kwargs): pass
def get_clone_cycles(*args, **kwargs): return []
def cleanup_old_data(*args, **kwargs): pass

import pytest
import db

def test_db_balance_save_and_load(memory_db):
    """Test saving and loading the agent's main balance memory."""
    # Memory DB is initialized automatically via conftest.py
    
    # Save test balance
    db.save_balance(balance=15.5, win_count=3, closed_count=5, total_pnl=2.5)
    
    # Load and assert
    saved = db.load_balance(default=0.0)
    
    assert saved["balance"] == 15.5
    assert saved["win_count"] == 3
    assert saved["closed_count"] == 5
    assert saved["total_pnl"] == 2.5

def test_db_load_fallback(memory_db):
    """Test fallback initialization if db returns missing."""
    import sqlite3
    # Wipe the table temporarily
    conn = sqlite3.connect(db.DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM agent_state")
    conn.commit()
    conn.close()
    
    loaded = db.load_balance(default=100.0)
    assert loaded["balance"] == 100.0
    assert loaded["win_count"] == 0

import pytest
import sqlite3
import os

# Fixture to mock SQLite database in memory
@pytest.fixture(scope="session", autouse=True)
def memory_db():
    """
    Forces the database connection to use a temporary DB
    to avoid overwriting the real DB during testing.
    """
    import tempfile
    import db
    temp_db = tempfile.NamedTemporaryFile(delete=False)
    db.DB_PATH = temp_db.name
    temp_db.close()
    
    # Initialize basic tables
    db.init_db()
    
    yield
    
    import os
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    # No teardown needed for :memory: as it disappears when connection closes

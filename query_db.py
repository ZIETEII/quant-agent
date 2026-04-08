from dotenv import load_dotenv
load_dotenv()
from src.core.db import get_conn
from psycopg2.extras import RealDictCursor
import json

with get_conn() as conn:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM clone_state")
        print(json.dumps([dict(r) for r in cur.fetchall()], default=str))

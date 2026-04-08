import os
import psycopg2
import sys

# Load environment variable if present. Locally, python might load it via dotenv or the user passes it.
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    # Intenta cargar de .env local si existe
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                if line.startswith("DATABASE_URL="):
                    DATABASE_URL = line.strip().split("=", 1)[1]
                    break

if not DATABASE_URL:
    print("⚠️ No se encontro DATABASE_URL. Saltando borrado en Postgres.")
    sys.exit(0)

print("🔌 Conectando a Supabase PostgreSQL para limpiar base de datos...")
try:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    tables = [
        "trades", "daily_stats", "agent_params", 
        "agent_state", "agent_insights", "clone_state", 
        "clone_cycles", "equity_history"
    ]
    
    query = f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE;"
    cur.execute(query)
    
    conn.commit()
    cur.close()
    conn.close()
    print("   ✓ Todas las tablas de Supabase han sido vaciadas con éxito.")
except Exception as e:
    print(f"❌ Error vaciando la base de datos de Supabase: {e}")
    sys.exit(1)

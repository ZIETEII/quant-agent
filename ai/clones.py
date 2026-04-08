"""
Módulo de Identidades de Shadow Trading (Clones Virtuales).
Permite mantener parámetros separados simulando ser multicerebros.
"""

# Definición inmutable del "ADN" orginal de los clones
CLONE_PROFILES = {
    "clone_conservador": {
        "name": "Turtle (Conservador)",
        "params": {
            "MIN_SCORE": "3",          # Exige los 3 timeframes siempre
            "RSI_OVERSOLD": "30.0",    # Compra solo caídas extremas
            "RSI_OVERBOUGHT": "60.0",  # Vende al mínimo signo de retroceso
            "RISK_PERCENT": "0.15"     # Arriesga menos capital
        }
    },
    "clone_scalper": {
        "name": "Ninja (Scalper)",
        "params": {
            "MIN_SCORE": "1",          # Compra rápido si hay confirmación menor
            "RSI_OVERSOLD": "45.0",    # Compra caídas moderadas 
            "RSI_OVERBOUGHT": "70.0",  # Deja correr un poco más
            "RISK_PERCENT": "0.30"     # Mayor exposición
        }
    },
    "clone_inercia": {
        "name": "Trend (Inercia)",
        "params": {
            "MIN_SCORE": "3",          # Exige los 3 TF alineados (tendencia fuerte)
            "RSI_OVERSOLD": "20.0",    # Solo compra caídas muy extremas (capitulación)
            "RSI_OVERBOUGHT": "80.0",  # Deja correr mucho la ganancia antes de vender
            "RISK_PERCENT": "0.25"     # Apuesta más en tendencias confirmadas
        }
    }
}

def get_clone_profiles():
    return CLONE_PROFILES

def evaluate_multi_armed_bandit():
    """
    Simplex Multi-Armed Bandit:
    Compara el rendimiento de todos los Clones vs Main en los últimos 7 días.
    Retorna (agent_id, dict_params) si hay un clon que supera notablemente al main, o None.
    """
    import sqlite3
    import os
    DB_PATH = os.path.join(os.path.dirname(__file__), "..", "quant_memory.db")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        
        # Rendimiento de los últimos 7 días
        rows = conn.execute('''
            SELECT agent_id, SUM(pnl_pct) as total_pct, COUNT(*) as trades, 
                   SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins
            FROM trades
            WHERE closed_at >= datetime('now', '-7 days', 'localtime')
            GROUP BY agent_id
        ''').fetchall()
        conn.close()

        stats = {r["agent_id"]: dict(r) for r in rows}
        if "main" not in stats:
            return None # Sin datos base
            
        main_pct = stats["main"]["total_pct"] or 0
        
        best_clone = None
        best_pct = main_pct
        
        for a_id in CLONE_PROFILES.keys():
            if a_id in stats:
                c_pct = stats[a_id]["total_pct"] or 0
                c_trades = stats[a_id]["trades"]
                # Debe superar a "main" por al menos +2.0% y haber ejecutado trades
                if c_pct > best_pct + 2.0 and c_trades >= 3:
                    best_pct = c_pct
                    best_clone = a_id

        if best_clone:
            return best_clone, CLONE_PROFILES[best_clone]
            
        return None
    except Exception as e:
        print("Error Bandido:", e)
        return None

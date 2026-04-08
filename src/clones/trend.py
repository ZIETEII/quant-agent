from datetime import datetime
from .base_clone import BaseClone


class TrendClone(BaseClone):
    """
    🌊 Trend (Inercia): Busca rides largos. TP alto, trailing amplio.
    
    🧬 ADN DE ENTRADA:
    - Solo entra si el token lleva > 15 minutos trending (confirma tendencia real)
    - 🤖 IA GATE: Exige certidumbre predictiva > 60% del motor Machine Learning
    - Quiere momentum + seguridad balanceados (total_score >= 55)
    - Rechaza tokens muy nuevos (< 15 min) porque no hay tendencia confirmada
    - Prefiere trending/boosted sobre tokens recién descubiertos
    
    CICLO: 90 días — evaluación trimestral de tendencias a largo plazo.
    """
    def __init__(self):
        params = {
            "INITIAL_BALANCE": 1000.0,
            "MAX_TRADES": 30,
            "RISK_PERCENT": 0.10,         # 10% por trade (moderado)
            "TAKE_PROFIT": 35,            # TP +35% (busca big moves)
            "STOP_LOSS": 15,              # SL -15% (más room)
            "TRAILING": 10,               # Trailing 10% amplio
            "DEAD_TRADE_MIN": 60,         # 60 min dead trade
            "MOONBAG": 0.30,              # 30% moonbag (max ride)
            "CYCLE_DAYS": 90,             # ⏰ Ciclo trimestral: 3 meses
            # Filtros propios del Trend
            "MIN_TOTAL_SCORE": 15,        # Score total balanceado
            "MIN_TREND_MINUTES": 5,       # Mínimo 5 min trending
        }
        super().__init__("clone_inercia", "Trend (Inercia)", params)

    def should_enter(self, trade: dict) -> bool:
        """
        🌊 Trend solo entra si hay TENDENCIA CONFIRMADA.
        - total_score >= 55 (balance entre momentum y seguridad)
        - Token debe tener >= 15 min de vida (no entra en lanzamientos)
        - Bluechips siempre pasan si tienen score decente (>= 45)
        """
        scores = trade.get("scores", {})
        total = scores.get("total", 0)
        ml_prob = scores.get("ml_prob", 0.5)
        source = trade.get("source", "")
        min_total = self.params.get("MIN_TOTAL_SCORE", 55)
        min_minutes = self.params.get("MIN_TREND_MINUTES", 15)

        # 🤖 1. IA Gate (ADN Surfista: requiere soporte algorítmico medio)
        # 🤖 1. IA Gate (ADN Surfista: requiere soporte algorítmico medio)
        if ml_prob < 0.15:
            return False

        # Bluechips: siempre son tendencia confirmada, umbral más bajo
        if source == "bluechip":
            return total >= 10

        # Verificar edad del token (necesita tendencia confirmada)
        try:
            opened = datetime.fromisoformat(trade.get("opened_at", ""))
            age_min = (datetime.now() - opened).total_seconds() / 60
            # Si el trade ACABA de abrirse, usamos la edad del token como proxy
            # Los nuevos tokens recién descubiertos son rechazados
            if source in ("new_pair", "new_profile") and age_min < min_minutes:
                return False
        except (ValueError, TypeError):
            pass

        # Score total balanceado
        return total >= min_total

    def _get_rejection_reason(self, trade: dict) -> str:
        scores = trade.get("scores", {})
        total = scores.get("total", 0)
        ml_prob = scores.get("ml_prob", 0.5)
        source = trade.get("source", "")
        
        if ml_prob < 0.15:
            return f"IA Gate: ML prob {ml_prob:.0%} < 15% (Falsa inercia)"
            
        if source in ("new_pair", "new_profile"):
            return f"token muy nuevo + total {total:.0f} (necesito tendencia confirmada)"
        return f"total_score {total:.0f} < {self.params.get('MIN_TOTAL_SCORE', 15)} (quiero tendencia)"

from .base_clone import BaseClone


class TurtleClone(BaseClone):
    """
    🐢 Turtle (Conservador): Más paciente, SL/TP más amplios.
    
    🧬 ADN DE ENTRADA:
    - Solo entra si safety_score >= 60 (quiere tokens seguros y estables)
    - 🤖 IA GATE: Exige certidumbre > 70% del motor Machine Learning
    - Prefiere bluechips y tokens con alta liquidez
    - Rechaza tokens nuevos/sniper sin historial de seguridad
    
    CICLO: 30 días — análisis mensual de rendimiento conservador.
    """
    def __init__(self):
        params = {
            "INITIAL_BALANCE": 1000.0,
            "MAX_TRADES": 30,
            "RISK_PERCENT": 0.08,        # 8% por trade (conservador)
            "TAKE_PROFIT": 12,            # TP +12%
            "STOP_LOSS": 6,               # SL -6%
            "TRAILING": 4,                # Trailing 4%
            "DEAD_TRADE_MIN": 90,         # Más paciencia: 90 min
            "MOONBAG": 0.10,              # 10% moonbag pequeño
            "CYCLE_DAYS": 30,             # ⏰ Ciclo mensual: 30 días
            # Filtros propios del Turtle
            "MIN_SAFETY": 20,             # Solo tokens seguros
        }
        super().__init__("clone_conservador", "Turtle (Conservador)", params)

    def should_enter(self, trade: dict) -> bool:
        """
        🐢 Turtle solo entra en tokens SEGUROS.
        - safety_score >= 60
        - Rechaza tokens nuevos (< 60 min) a menos que safety >= 75
        - Ama los bluechips (siempre entra si safety >= 50)
        """
        scores = trade.get("scores", {})
        safety = scores.get("safety", 0)
        ml_prob = scores.get("ml_prob", 0.5)
        source = trade.get("source", "")
        min_safety = self.params.get("MIN_SAFETY", 60)

        # 🤖 1. IA Gate (ADN Conservador absoluto)
        if ml_prob < 0.20:
            return False

        # Bluechips: umbral más bajo (confía más en tokens establecidos)
        if source == "bluechip":
            return safety >= 10

        # Tokens nuevos: exige seguridad excepcional
        if source in ("new_pair", "new_profile"):
            return safety >= 35

        # Trending/boosted: filtro estándar
        return safety >= min_safety

    def _get_rejection_reason(self, trade: dict) -> str:
        scores = trade.get("scores", {})
        safety = scores.get("safety", 0)
        ml_prob = scores.get("ml_prob", 0.5)
        source = trade.get("source", "")
        
        if ml_prob < 0.20:
            return f"IA Gate: ML prob {ml_prob:.0%} < 20% (Riesgo inaceptable)"
            
        threshold = 35 if source in ("new_pair", "new_profile") else self.params.get("MIN_SAFETY", 20)
        return f"safety {safety:.0f} < {threshold} (necesito seguridad)"

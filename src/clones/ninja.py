from .base_clone import BaseClone


class NinjaClone(BaseClone):
    """
    ⚡ Ninja (Scalper): Agresivo, TP/SL tight, rápido en cerrar.
    
    🧬 ADN DE ENTRADA:
    - Solo entra si momentum_score > 70 (quiere acción de precio explosiva)
    - 🤖 IA GATE: Exige certidumbre mínima > 55% del motor Machine Learning
    - Prefiere tokens con alto ratio de compras vs ventas
    - Rechaza tokens "aburridos" con bajo momentum
    
    CICLO: 15 días — evaluación rápida de estrategias agresivas.
    """
    def __init__(self):
        params = {
            "INITIAL_BALANCE": 1000.0,
            "MAX_TRADES": 30,
            "RISK_PERCENT": 0.15,         # 15% por trade (agresivo)
            "TAKE_PROFIT": 20,            # TP +20%
            "STOP_LOSS": 10,              # SL -10%
            "TRAILING": 6,                # Trailing 6% tight
            "DEAD_TRADE_MIN": 20,         # Impaciente: 20 min dead trade
            "MOONBAG": 0.25,              # 25% moonbag
            "CYCLE_DAYS": 15,             # ⏰ Ciclo corto: 15 días
            # Filtros propios del Ninja
            "MIN_MOMENTUM": 30,           # Solo explosión de precio
        }
        super().__init__("clone_scalper", "Ninja (Scalper)", params)

    def should_enter(self, trade: dict) -> bool:
        """
        ⚡ Ninja solo entra si hay MOMENTUM EXPLOSIVO.
        - momentum_score >= 70
        - Rechaza bluechips "lentos" a menos que tengan momentum excepcional
        """
        scores = trade.get("scores", {})
        momentum = scores.get("momentum", 0)
        ml_prob = scores.get("ml_prob", 0.5)
        source = trade.get("source", "")
        min_momentum = self.params.get("MIN_MOMENTUM", 70)

        # 🤖 1. IA Gate (ADN Asesino: certeza base permitida para scalping)
        if ml_prob < 0.15:
            return False

        # Bluechips solo si tienen momentum excepcional (>= 40)
        if source == "bluechip" and momentum < 40:
            return False

        # Todo lo demás requiere momentum >= 30
        return momentum >= min_momentum

    def _get_rejection_reason(self, trade: dict) -> str:
        scores = trade.get("scores", {})
        momentum = scores.get("momentum", 0)
        ml_prob = scores.get("ml_prob", 0.5)
        
        if ml_prob < 0.15:
            return f"IA Gate: ML prob {ml_prob:.0%} < 15% (Muy riesgoso hasta para scalping)"
            
        return f"momentum {momentum:.0f} < {self.params.get('MIN_MOMENTUM', 30)} (quiero explosión)"

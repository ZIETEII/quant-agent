"""
Módulo Predictor de Machine Learning (RandomForestClassifier).
Analiza el historial de trades cerrados en SQLite y genera probabilidades.
"""

import os
import joblib
import logging
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

import db

log = logging.getLogger("AgenteBot.AI")

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "agent_model.pkl")

_cached_model = None

# Definir mapeos para categorías a valores numéricos
REGIME_MAP = {"BULL": 1, "SIDEWAYS": 0, "BEAR": -1}

def map_regime(val):
    if not val:
        return 0
    return REGIME_MAP.get(str(val).upper(), 0)

def train_model():
    """Entrena el RandomForestClassifier si hay datos suficientes."""
    try:
        data = db.get_training_data()
        
        if len(data) < 30:
            log.info(f"[ML] Muy pocos datos para entrenar (solo {len(data)}/30).")
            return False

        df = pd.DataFrame(data)
        
        # Mapeo textual a numérico
        df["market_regime"] = df["market_regime"].apply(map_regime)
        # Result "win" -> 1, "loss" -> 0
        df["label"] = df["result"].apply(lambda x: 1 if x == "win" else 0)

        # Preparamos las features
        features = ["rsi_at_entry", "macd_at_entry", "tf_score", "ema_alignment", "market_regime", "bb_width", "bb_position"]
        X = df[features].fillna(0)
        y = df["label"]

        model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
        model.fit(X, y)

        # Asegurarse que la carpeta data exista
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        joblib.dump(model, MODEL_PATH)

        global _cached_model
        _cached_model = model

        log.info(f"🧠 [ML] Modelo re-entrenado en RAM y volcado a disco con {len(df)} muestras.")
        return True
    except Exception as e:
        log.error(f"[ML] Error al entrenar: {e}")
        return False

def predict_trade_probability(rsi: float, macd: float, tf_score: int, ema_align: int, regime: str, bb_width: float, bb_position: float) -> float:
    """Devuelve la probabilidad de victoria (0.0 a 1.0). Si no hay modelo, devuelve 0.5 por defecto."""
    global _cached_model
    
    if _cached_model is None:
        if not os.path.exists(MODEL_PATH):
            return 0.5  # No hay modelo, neutralidad algorítmica
        try:
            _cached_model = joblib.load(MODEL_PATH)
            log.info("🧠 [ML] Modelo cargado desde disco hacia memoria RAM exitosamente.")
        except Exception as e:
            log.error(f"[ML] Error cargando modelo desde disco: {e}")
            return 0.5

    try:
        model = _cached_model
        rg = map_regime(regime)
        
        X_pred = pd.DataFrame([{
            "rsi_at_entry": rsi,
            "macd_at_entry": macd,
            "tf_score": tf_score,
            "ema_alignment": ema_align,
            "market_regime": rg,
            "bb_width": bb_width,
            "bb_position": bb_position
        }])
        
        # predict_proba retorna arreglo de probas: [prob_clase_0, prob_clase_1]
        probs = model.predict_proba(X_pred)
        # Si el modelo solo ha visto "wins" o "losses" (clase unica), hay que validar la forma
        if len(model.classes_) == 2 and model.classes_[1] == 1:
            win_prob = float(probs[0][1])
        else:
            win_prob = float(model.predict(X_pred)[0])  # fallback si solo hay 1 clase

        return win_prob
    except Exception as e:
        log.warning(f"[ML] No se pudo predecir: {e}")
        return 0.5

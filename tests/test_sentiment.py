import pytest
from ai.sentiment import classify_sentiment, classify_market_heat, calculate_risk_modifier, sentiment_state, get_risk_modifier

def test_classify_sentiment():
    """Test the Fear & Greed classification mapping."""
    assert classify_sentiment(10) == "EXTREME_FEAR"
    assert classify_sentiment(30) == "FEAR"
    assert classify_sentiment(50) == "NEUTRAL"
    assert classify_sentiment(70) == "GREED"
    assert classify_sentiment(85) == "EXTREME_GREED"

def test_classify_market_heat():
    """Test Funding Rate sum heat detection."""
    # Sum is > 0.05
    assert classify_market_heat(0.06, 0.06) == "OVERHEATED"
    # Is Cold
    assert classify_market_heat(0.001, 0.001) == "COLD"
    # Is Normal
    assert classify_market_heat(0.01, 0.01) == "NORMAL"

def test_calculate_risk_modifier():
    """Test risk multiplier math."""
    # Base: EXTREME_FEAR = 1.25
    # Heat: COLD = * 1.10 = 1.375
    # Funding BTC (-0.03) = * 1.15 = 1.58
    # Clamped to 1.30 max
    mod = calculate_risk_modifier(signal="EXTREME_FEAR", heat="COLD", funding_btc=-0.03)
    assert pytest.approx(mod, 0.01) == 1.30

    # Base: NEUTRAL = 1.0
    # Heat: OVERHEATED = * 0.70 = 0.70
    # Funding BTC (0.04) = * 0.80 = 0.56
    mod2 = calculate_risk_modifier(signal="NEUTRAL", heat="OVERHEATED", funding_btc=0.04)
    assert pytest.approx(mod2, 0.01) == 0.56

def test_get_risk_modifier_extreme_fear_trigger():
    """Test that EXTREME_FEAR hard-blocks purchases by returning 0."""
    # Set state
    sentiment_state["sentiment_signal"] = "EXTREME_FEAR"
    sentiment_state["risk_modifier"] = 0.5  # Internal base
    
    assert get_risk_modifier() == 0.0
    
    # Set state neutral
    sentiment_state["sentiment_signal"] = "NEUTRAL"
    sentiment_state["risk_modifier"] = 0.85
    
    assert get_risk_modifier() == 0.85

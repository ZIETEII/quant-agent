import pytest
from ai.kelly_criterion import calculate_kelly_fraction, get_kelly_risk, KELLY_MAX, KELLY_MIN

def test_calculate_kelly_fraction_no_data():
    """Test Kelly math returns None if stats are None."""
    assert calculate_kelly_fraction(None) is None

def test_calculate_kelly_fraction_good_edge():
    """Test standard Kelly edge (Win Rate > 50%, Ratio > 1)"""
    # Win Rate = 60%, Avg Win / Avg Loss = 1.5
    # Full Kelly = 0.6 - ( (1 - 0.6) / 1.5 ) = 0.6 - (0.4 / 1.5) = 0.6 - 0.266 = 0.333
    # Half Kelly = 0.166
    stats = {
        "win_rate": 0.60,
        "ratio": 1.5,
        "total_trades": 20
    }
    kf = calculate_kelly_fraction(stats)
    assert kf is not None
    assert 0.15 < kf < 0.18
    assert kf <= KELLY_MAX

def test_calculate_kelly_fraction_bad_edge():
    """Test Kelly edge when Win Rate is terrible, should return KELLY_MIN or clamped safe value."""
    # Win Rate = 30%, Ratio = 1.0
    # Full Kelly = 0.3 - (0.7 / 1.0) = -0.4 (Negative Edge)
    stats = {
        "win_rate": 0.30,
        "ratio": 1.0,
        "total_trades": 20
    }
    kf = calculate_kelly_fraction(stats)
    # The code clamps negative/zero Kelly to KELLY_MIN
    assert kf == KELLY_MIN

def test_get_kelly_risk_modifiers(monkeypatch):
    """Test that regime and score modifying layer works correctly."""
    
    # Mock calculate_kelly_fraction to return a fixed 0.10 for testing
    monkeypatch.setattr("ai.kelly_criterion.calculate_kelly_fraction", lambda days: 0.10)
    
    # Base = 0.10. Score 3, Regime BULL = modifier 1.20 => 0.12
    risk = get_kelly_risk(b_score=3, regime="BULL")
    assert pytest.approx(risk) == 0.12
    
    # Base = 0.10. Score 2, Regime BEAR = modifier 0.50 => 0.05
    risk_bear = get_kelly_risk(b_score=2, regime="BEAR")
    assert pytest.approx(risk_bear) == 0.05
    
    # Base = 0.10. Regime SIDEWAYS = modifier 0.70 => 0.07
    risk_side = get_kelly_risk(b_score=2, regime="SIDEWAYS")
    assert pytest.approx(risk_side) == 0.07

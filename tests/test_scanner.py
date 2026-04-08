import pytest
from scanner.token_scanner import TokenScanner

@pytest.fixture
def scanner():
    return TokenScanner()

def test_passes_safety_filter_bluechip(scanner):
    """Test safety filter allows high liquid bluechip-style tokens."""
    token = {
        "symbol": "WIF",
        "price_usd": 3.0,
        "liquidity_usd": 2500000,
        "volume_24h": 5000000,
        "market_cap": 300000000
    }
    assert scanner._passes_safety_filter(token) is True

def test_passes_safety_filter_low_liq(scanner):
    """Test safety filter rejects tokens with liquidity < 5000."""
    token = {
        "symbol": "WIF",
        "price_usd": 3.0,
        "liquidity_usd": 4000, # Below 5k
        "volume_24h": 5000000,
        "market_cap": 300000000
    }
    assert scanner._passes_safety_filter(token) is False

def test_passes_sniper_filter_new(scanner):
    """Test sniper filter aggressively filtering low action meme new tokens."""
    # Good Token
    good_token = {
        "symbol": "DOGE2",
        "price_usd": 0.001,
        "liquidity_usd": 5000,
        "volume_5m": 1500,
        "txns_buys_5m": 10
    }
    assert scanner._passes_sniper_filter(good_token) is True

    # Bad Token (Low Buys)
    bad_token = {
        "symbol": "CAT4",
        "price_usd": 0.001,
        "liquidity_usd": 5000,
        "volume_5m": 1500,
        "txns_buys_5m": 3 # Target is > 5
    }
    assert scanner._passes_sniper_filter(bad_token) is False

    # Bad Token (Low 5m Volume)
    bad_vol_token = {
        "symbol": "RUG",
        "price_usd": 0.001,
        "liquidity_usd": 5000,
        "volume_5m": 200, # Target is > 500
        "txns_buys_5m": 10
    }
    assert scanner._passes_sniper_filter(bad_vol_token) is False

def test_momentum_calc_high(scanner):
    """Test momentum scoring logic."""
    token = {
        "volume_5m": 60000, # +30
        "txns_buys_5m": 80,
        "txns_sells_5m": 10, # buy ratio > 0.75 => +25
        "price_change_5m": 60 # > 50 => +25
    }
    # Total so far: 30 + 25 + 25 = 80
    score = scanner._calc_momentum_score(token)
    assert score >= 80

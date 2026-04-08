"""
╔══════════════════════════════════════════════════════════╗
║   TOKEN SCANNER — Descubrimiento de Tokens Solana        ║
║   Modo Trending: Top tokens por volumen/momentum         ║
║   Modo Sniper:   Nuevos lanzamientos (Pump.fun/Raydium)  ║
╚══════════════════════════════════════════════════════════╝
"""

import logging
import time
import os
import aiohttp
import asyncio
from datetime import datetime, timedelta

log = logging.getLogger("AgenteBot.Scanner")

# ── Mints que NO hay que tradear ──
BLACKLIST_MINTS = {
    "So11111111111111111111111111111111111111112",    # SOL nativo
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",  # mSOL
    "7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj", # stSOL
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn", # jitoSOL
    "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",  # bSOL
}

# Stablecoins conocidos
STABLECOIN_SYMBOLS = {"USDC", "USDT", "DAI", "BUSD", "TUSD", "USDP", "FRAX", "USDD", "LUSD"}

# ══════════════════════════════════════════════════════════
#  💎 TOP SOLANA BLUECHIP TOKENS (curated, high-liquidity)
# ══════════════════════════════════════════════════════════
SOLANA_BLUECHIPS = [
    # ── Major Global Crypto (Wormhole/Portal wrapped on Solana) ──
    {"mint": "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh", "symbol": "wBTC",   "name": "Bitcoin (Wormhole)"},
    {"mint": "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs", "symbol": "wETH",   "name": "Ethereum (Wormhole)"},
    {"mint": "cbbtcf3aa214zXHbiAZQGr4PGzizYoneftUZRrrfKBMR",  "symbol": "cbBTC",  "name": "Coinbase BTC"},
    {"mint": "9gP2kCy3wA1ctvYWQk75guqXuHfrEomqydHLtcTCqiLa", "symbol": "wBNB",   "name": "BNB (Wormhole)"},
    {"mint": "Gz7VkD4MacbEB6yC5XD3HcumEiYx2EtDYYrfikGsvopG", "symbol": "wMATIC", "name": "Polygon (Wormhole)"},
    {"mint": "KgV1GvrHQmRBY8sHQQeUKwTm2r2h8t4C8qt12Cw1HVE",  "symbol": "wAVAX",  "name": "Avalanche (Wormhole)"},
    {"mint": "2wpTofQ8SkACrkZWrZDjRPnE2w5Dce2S89ari41tVfc3", "symbol": "wLINK",  "name": "Chainlink (Wormhole)"},
    {"mint": "8FU95xFJhUUkyyCLU13HSzDLs7oC4QZdXQHL6SCeab36", "symbol": "wUNI",   "name": "Uniswap (Wormhole)"},
    {"mint": "HysWcbHiYY9888pHbaqhwLYZQeZrcQMXKQWRqS7vAiG5", "symbol": "wAXS",   "name": "Axie (Wormhole)"},
    # ── Top Solana Ecosystem ──
    {"mint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",  "symbol": "JUP",    "name": "Jupiter"},
    {"mint": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", "symbol": "WIF",    "name": "dogwifhat"},
    {"mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", "symbol": "BONK",   "name": "Bonk"},
    {"mint": "rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof",  "symbol": "RENDER", "name": "Render"},
    {"mint": "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R", "symbol": "RAY",    "name": "Raydium"},
    {"mint": "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE",  "symbol": "ORCA",   "name": "Orca"},
    {"mint": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3", "symbol": "PYTH",   "name": "Pyth Network"},
    {"mint": "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5",  "symbol": "MEW",    "name": "cat in a dogs world"},
    {"mint": "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL",  "symbol": "JTO",    "name": "Jito"},
    {"mint": "85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ", "symbol": "W",      "name": "Wormhole"},
    {"mint": "TNSRxcUxoT9xBG3de7PiJyTDYu7kskLqcpddxnEJAS6", "symbol": "TNSR",   "name": "Tensor"},
    {"mint": "27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4", "symbol": "JLP",    "name": "Jupiter LP"},
    {"mint": "SHDWyBxihqiCj6YekG2GUr7wqKLeLAMK1gHZck9pL6y",  "symbol": "SHDW",   "name": "Shadow Token"},
    {"mint": "MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey",  "symbol": "MNDE",   "name": "Marinade"},
    {"mint": "DriFtupJYLTosbwoN8koMbEYSx54aFAVLddWsbksjwg7", "symbol": "DRIFT",  "name": "Drift Protocol"},
    {"mint": "nosXBVoaCTtYdLvKY6Csb4AC8JCdQKKAaWYtx2ZMoo7",  "symbol": "NOS",    "name": "Nosana"},
    {"mint": "HeLp6NuQkmYB4pYWo2zYs22mESHXPQYzXbB8n4V98jwC", "symbol": "AI16Z",  "name": "ai16z"},
    {"mint": "Grass7B4RdKfBCjTKgSqnXkqjwiGvQyFbuSCUJr3XXjs",  "symbol": "GRASS",  "name": "Grass"},
    {"mint": "ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82",  "symbol": "BOME",   "name": "Book of Meme"},
    {"mint": "A8C3egyqMoMY5kB3bkEJ32pRhMGBRFDQGCcE8YGpump",  "symbol": "FARTCOIN","name": "Fartcoin"},
]
BLUECHIP_MINTS = set(bc["mint"] for bc in SOLANA_BLUECHIPS)


class TokenScanner:
    """
    Escanea el ecosistema Solana para descubrir tokens con potencial.
    Usa DexScreener API para datos de mercado reales.
    Modo Híbrido: Bluechips + Memecoins Sniper.
    """

    def __init__(self):
        self._trending_cache = []
        self._trending_ts = 0
        self._trending_ttl = 30  # refresh cada 30s
        
        self._new_tokens_cache = []
        self._new_tokens_ts = 0
        self._new_tokens_ttl = 15  # refresh cada 15s

        self._bluechip_cache = []
        self._bluechip_ts = 0
        self._bluechip_ttl = 20  # refresh cada 20s
        
        self._pool_address_cache = {} # {mint: pool_address}

    # ══════════════════════════════════════════════════════════
    #  💎 MODO BLUECHIP — Top Solana Ecosystem Tokens
    # ══════════════════════════════════════════════════════════

    async def scan_bluechips(self, limit: int = 20) -> list:
        """
        Escanea los tokens top de Solana (curated list).
        Usa DexScreener para datos de mercado en tiempo real.
        Solo retorna los que tienen momentum positivo.
        """
        if (time.time() - self._bluechip_ts) < self._bluechip_ttl and self._bluechip_cache:
            return self._bluechip_cache[:limit]

        tokens = []
        try:
            async with aiohttp.ClientSession() as session:
                # Buscar datos de todos los bluechips via DexScreener
                mints = ",".join(bc["mint"] for bc in SOLANA_BLUECHIPS)
                url = f"https://api.dexscreener.com/tokens/v1/solana/{mints}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
                    if r.status != 200:
                        return self._bluechip_cache[:limit]
                    pairs = await r.json()

                    # Agrupar: mejor par por token (mayor liquidez)
                    best_pairs = {}
                    if isinstance(pairs, list):
                        for pair in pairs:
                            base = pair.get("baseToken", {})
                            mint = base.get("address", "")
                            liq = float(pair.get("liquidity", {}).get("usd", 0) or 0)
                            if mint not in best_pairs or liq > best_pairs[mint].get("_liq", 0):
                                pair["_liq"] = liq
                                best_pairs[mint] = pair

                    # Construir lista de tokens con datos
                    for bc in SOLANA_BLUECHIPS:
                        mint = bc["mint"]
                        pair = best_pairs.get(mint)
                        if not pair:
                            continue

                        base = pair.get("baseToken", {})
                        token = {
                            "mint": mint,
                            "symbol": bc["symbol"],
                            "name": bc["name"],
                            "source": "bluechip",
                            "pair_address": pair.get("pairAddress", ""),
                            "price_usd": float(pair.get("priceUsd", 0) or 0),
                            "volume_24h": float(pair.get("volume", {}).get("h24", 0) or 0),
                            "volume_1h": float(pair.get("volume", {}).get("h1", 0) or 0),
                            "volume_5m": float(pair.get("volume", {}).get("m5", 0) or 0),
                            "price_change_5m": float(pair.get("priceChange", {}).get("m5", 0) or 0),
                            "price_change_1h": float(pair.get("priceChange", {}).get("h1", 0) or 0),
                            "price_change_24h": float(pair.get("priceChange", {}).get("h24", 0) or 0),
                            "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0) or 0),
                            "market_cap": float(pair.get("marketCap", 0) or 0),
                            "fdv": float(pair.get("fdv", 0) or 0),
                            "txns_buys_5m": pair.get("txns", {}).get("m5", {}).get("buys", 0),
                            "txns_sells_5m": pair.get("txns", {}).get("m5", {}).get("sells", 0),
                            "txns_buys_1h": pair.get("txns", {}).get("h1", {}).get("buys", 0),
                            "txns_sells_1h": pair.get("txns", {}).get("h1", {}).get("sells", 0),
                            "dex_url": pair.get("url", ""),
                        }

                        # Solo incluir si tiene precio y liquidez
                        if token["price_usd"] > 0 and token["liquidity_usd"] > 10000:
                            tokens.append(token)

                # Ordenar por cambio de precio 1h (momentum)
                tokens.sort(key=lambda x: x.get("price_change_1h", 0), reverse=True)
                self._bluechip_cache = tokens
                self._bluechip_ts = time.time()
                return tokens[:limit]

        except Exception as e:
            log.warning(f"Bluechip scan error: {e}")
            return self._bluechip_cache[:limit]

    def score_bluechip(self, token: dict) -> dict:
        """
        Scoring especializado para bluechips.
        Más conservador que memecoins: prioriza momentum estable.
        """
        score = 0

        # ── Momentum 1H (peso: 35) ──
        chg_1h = token.get("price_change_1h", 0)
        if chg_1h > 8: score += 35       # Rally fuerte
        elif chg_1h > 4: score += 30
        elif chg_1h > 2: score += 25
        elif chg_1h > 0.5: score += 15
        elif chg_1h > 0: score += 8
        elif chg_1h > -2: score += 3     # Neutral
        elif chg_1h < -5: score -= 10    # Bajando fuerte

        # ── Volumen vs promedio (peso: 25) ──
        vol_5m = token.get("volume_5m", 0)
        vol_1h = token.get("volume_1h", 0)
        if vol_1h > 0 and vol_5m > 0:
            # Si vol de 5min es alto relativo a la hora = aceleración
            ratio = (vol_5m * 12) / vol_1h
            if ratio > 2.0: score += 25   # Volumen acelerando mucho
            elif ratio > 1.5: score += 20
            elif ratio > 1.0: score += 15
            elif ratio > 0.5: score += 8

        # ── Buy pressure (peso: 20) ──
        buys = token.get("txns_buys_5m", 0)
        sells = token.get("txns_sells_5m", 0)
        if buys + sells > 0:
            buy_ratio = buys / (buys + sells)
            if buy_ratio > 0.70: score += 20
            elif buy_ratio > 0.60: score += 15
            elif buy_ratio > 0.55: score += 10
            elif buy_ratio > 0.50: score += 5

        # ── Tendencia 24h (peso: 20) ──
        chg_24h = token.get("price_change_24h", 0)
        if chg_24h > 15: score += 20
        elif chg_24h > 8: score += 15
        elif chg_24h > 3: score += 10
        elif chg_24h > 0: score += 5
        elif chg_24h < -10: score -= 10

        total = max(0, min(100, score))
        return {
            "momentum": round(min(100, max(0, score)), 1),
            "safety": 85.0,  # Bluechips son inherentemente más seguros
            "timing": round(min(100, max(0, score * 0.8)), 1),
            "total": round(total, 1),
        }

    # ══════════════════════════════════════════════════════════
    #  📈 MODO TRENDING — Tokens con mayor momentum
    # ══════════════════════════════════════════════════════════

    async def scan_trending(self, limit: int = 30) -> list:
        """
        Obtiene los tokens de Solana con mayor volumen y momentum.
        Fuente: DexScreener API (boosted/trending tokens).
        
        Returns: Lista de dicts con token info + métricas
        """
        if (time.time() - self._trending_ts) < self._trending_ttl and self._trending_cache:
            return self._trending_cache[:limit]

        tokens = []
        try:
            async with aiohttp.ClientSession() as session:
                # DexScreener: Token profiles (trending en Solana)
                url = "https://api.dexscreener.com/token-boosts/top/v1"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        data = await r.json()
                        for item in data:
                            if item.get("chainId") != "solana":
                                continue
                            mint = item.get("tokenAddress", "")
                            if mint in BLACKLIST_MINTS:
                                continue
                            tokens.append({
                                "mint": mint,
                                "source": "boosted",
                                "boost_amount": item.get("totalAmount", 0),
                            })

                # Enriquecer con datos de pares de DexScreener
                enriched = await self._enrich_tokens(session, tokens[:50])
                
                # Filtrar y ordenar por volumen
                valid = [t for t in enriched if self._passes_safety_filter(t)]
                valid.sort(key=lambda x: x.get("volume_24h", 0), reverse=True)
                
                self._trending_cache = valid
                self._trending_ts = time.time()
                return valid[:limit]

        except Exception as e:
            log.warning(f"Trending scan error: {e}")
            return self._trending_cache[:limit]

    # ══════════════════════════════════════════════════════════
    #  🔫 MODO SNIPER — Tokens recién lanzados
    # ══════════════════════════════════════════════════════════

    async def scan_new_tokens(self, max_age_minutes: int = 60, limit: int = 20) -> list:
        """
        Descubre tokens nuevos lanzados en Solana en las últimas X minutos.
        Fuente: DexScreener latest pairs API.
        
        Returns: Lista de tokens nuevos con métricas
        """
        if (time.time() - self._new_tokens_ts) < self._new_tokens_ttl and self._new_tokens_cache:
            return self._new_tokens_cache[:limit]

        tokens = []
        try:
            async with aiohttp.ClientSession() as session:
                # DexScreener: Latest token profiles  
                url = "https://api.dexscreener.com/token-profiles/latest/v1"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        data = await r.json()
                        for item in data:
                            if item.get("chainId") != "solana":
                                continue
                            mint = item.get("tokenAddress", "")
                            if mint in BLACKLIST_MINTS:
                                continue
                            tokens.append({
                                "mint": mint,
                                "source": "new_profile",
                            })

                # También buscar los pares más recientes en Solana
                url2 = "https://api.dexscreener.com/latest/dex/pairs/solana"
                try:
                    async with session.get(url2, timeout=aiohttp.ClientTimeout(total=10)) as r:
                        if r.status == 200:
                            data = await r.json()
                            pairs = data.get("pairs", [])
                            for pair in pairs:
                                created_at = pair.get("pairCreatedAt", 0)
                                if created_at:
                                    age_ms = int(time.time() * 1000) - created_at
                                    age_min = age_ms / 60000
                                    if age_min > max_age_minutes:
                                        continue
                                
                                base = pair.get("baseToken", {})
                                mint = base.get("address", "")
                                symbol = base.get("symbol", "")
                                
                                if mint in BLACKLIST_MINTS:
                                    continue
                                if symbol.upper() in STABLECOIN_SYMBOLS:
                                    continue

                                existing = [t for t in tokens if t["mint"] == mint]
                                if existing:
                                    continue

                                tokens.append({
                                    "mint": mint,
                                    "source": "new_pair",
                                    "pair_address": pair.get("pairAddress", ""),
                                    "name": base.get("name", "Unknown"),
                                    "symbol": symbol,
                                    "price_usd": float(pair.get("priceUsd", 0) or 0),
                                    "volume_24h": float(pair.get("volume", {}).get("h24", 0) or 0),
                                    "volume_1h": float(pair.get("volume", {}).get("h1", 0) or 0),
                                    "volume_5m": float(pair.get("volume", {}).get("m5", 0) or 0),
                                    "price_change_5m": float(pair.get("priceChange", {}).get("m5", 0) or 0),
                                    "price_change_1h": float(pair.get("priceChange", {}).get("h1", 0) or 0),
                                    "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0) or 0),
                                    "market_cap": float(pair.get("marketCap", 0) or 0),
                                    "fdv": float(pair.get("fdv", 0) or 0),
                                    "txns_buys_5m": pair.get("txns", {}).get("m5", {}).get("buys", 0),
                                    "txns_sells_5m": pair.get("txns", {}).get("m5", {}).get("sells", 0),
                                    "txns_buys_1h": pair.get("txns", {}).get("h1", {}).get("buys", 0),
                                    "txns_sells_1h": pair.get("txns", {}).get("h1", {}).get("sells", 0),
                                    "created_at": created_at,
                                    "age_minutes": round(age_min, 1) if created_at else None,
                                    "dex_url": pair.get("url", ""),
                                })
                except:
                    pass

                # Enriquecer tokens que sólo tienen mint
                need_enrich = [t for t in tokens if "price_usd" not in t or t.get("price_usd", 0) == 0]
                if need_enrich:
                    enriched = await self._enrich_tokens(session, need_enrich)
                    # Merge enriched data back
                    enriched_map = {t["mint"]: t for t in enriched}
                    for t in tokens:
                        if t["mint"] in enriched_map:
                            t.update(enriched_map[t["mint"]])

                # Filtrar tokens válidos
                valid = [t for t in tokens if t.get("price_usd", 0) > 0 and self._passes_sniper_filter(t)]
                valid.sort(key=lambda x: x.get("volume_5m", 0), reverse=True)
                
                self._new_tokens_cache = valid
                self._new_tokens_ts = time.time()
                return valid[:limit]

        except Exception as e:
            log.warning(f"New token scan error: {e}")
            return self._new_tokens_cache[:limit]

    # ══════════════════════════════════════════════════════════
    #  🔍 ENRIQUECIMIENTO DE DATOS
    # ══════════════════════════════════════════════════════════

    async def _enrich_tokens(self, session: aiohttp.ClientSession, tokens: list) -> list:
        """Busca datos de mercado para una lista de tokens via DexScreener."""
        if not tokens:
            return []

        enriched = []
        # DexScreener permite hasta 30 tokens por request
        batch_size = 30
        for i in range(0, len(tokens), batch_size):
            batch = tokens[i:i+batch_size]
            mints = ",".join(t["mint"] for t in batch)
            
            try:
                url = f"https://api.dexscreener.com/tokens/v1/solana/{mints}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status != 200:
                        continue
                    pairs = await r.json()
                    
                    # Agrupar pares por token base
                    token_data = {}
                    if isinstance(pairs, list):
                        for pair in pairs:
                            base = pair.get("baseToken", {})
                            mint = base.get("address", "")
                            if mint not in token_data:
                                token_data[mint] = pair  # Usar el primer par (mayor liquidez)

                    for t in batch:
                        pair = token_data.get(t["mint"])
                        if pair:
                            base = pair.get("baseToken", {})
                            t.update({
                                "name": base.get("name", t.get("name", "Unknown")),
                                "symbol": base.get("symbol", t.get("symbol", "?")),
                                "pair_address": pair.get("pairAddress", ""),
                                "price_usd": float(pair.get("priceUsd", 0) or 0),
                                "volume_24h": float(pair.get("volume", {}).get("h24", 0) or 0),
                                "volume_1h": float(pair.get("volume", {}).get("h1", 0) or 0),
                                "volume_5m": float(pair.get("volume", {}).get("m5", 0) or 0),
                                "price_change_5m": float(pair.get("priceChange", {}).get("m5", 0) or 0),
                                "price_change_1h": float(pair.get("priceChange", {}).get("h1", 0) or 0),
                                "price_change_24h": float(pair.get("priceChange", {}).get("h24", 0) or 0),
                                "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0) or 0),
                                "market_cap": float(pair.get("marketCap", 0) or 0),
                                "fdv": float(pair.get("fdv", 0) or 0),
                                "txns_buys_5m": pair.get("txns", {}).get("m5", {}).get("buys", 0),
                                "txns_sells_5m": pair.get("txns", {}).get("m5", {}).get("sells", 0),
                                "txns_buys_1h": pair.get("txns", {}).get("h1", {}).get("buys", 0),
                                "txns_sells_1h": pair.get("txns", {}).get("h1", {}).get("sells", 0),
                                "created_at": pair.get("pairCreatedAt", 0),
                                "dex_url": pair.get("url", ""),
                            })
                            # Calcular edad
                            if t["created_at"]:
                                age_ms = int(time.time() * 1000) - t["created_at"]
                                t["age_minutes"] = round(age_ms / 60000, 1)
                        enriched.append(t)
            except Exception as e:
                log.warning(f"Enrich batch error: {e}")
                enriched.extend(batch)

        return enriched

    # ══════════════════════════════════════════════════════════
    #  🛡️ FILTROS DE SEGURIDAD
    # ══════════════════════════════════════════════════════════

    def _passes_safety_filter(self, token: dict) -> bool:
        """Filtro de seguridad para tokens trending."""
        liq = token.get("liquidity_usd", 0)
        vol = token.get("volume_24h", 0)
        mc = token.get("market_cap", 0) or token.get("fdv", 0)
        price = token.get("price_usd", 0)

        if price <= 0:
            return False
        if liq < 5000:  # Mínimo $5K liquidez
            return False
        if vol < 1000:  # Mínimo $1K volumen 24h
            return False
        if mc > 0 and mc < 5000:  # Market cap mínimo
            return False
        
        # Filtrar si no tiene símbool
        sym = token.get("symbol", "")
        if not sym or sym.upper() in STABLECOIN_SYMBOLS:
            return False

        return True

    def _passes_sniper_filter(self, token: dict) -> bool:
        """Filtro más agresivo para tokens nuevos (sniper mode)."""
        liq = token.get("liquidity_usd", 0)
        vol_5m = token.get("volume_5m", 0)
        price = token.get("price_usd", 0)
        buys_5m = token.get("txns_buys_5m", 0)

        if price <= 0:
            return False
        if liq < 2000:  # Mínimo $2K liquidez para nuevos tokens
            return False
        if vol_5m < 500:  # Al menos $500 de volumen en 5 min
            return False
        if buys_5m < 5:  # Al menos 5 compras en 5 min
            return False

        sym = token.get("symbol", "")
        if not sym or sym.upper() in STABLECOIN_SYMBOLS:
            return False

        return True

    # ══════════════════════════════════════════════════════════
    #  📊 SCORING
    # ══════════════════════════════════════════════════════════

    def score_token(self, token: dict) -> dict:
        """
        Calcula scores de momentum, safety y timing para un token.
        Cada score va de 0-100. Total score = promedio ponderado.
        """
        momentum = self._calc_momentum_score(token)
        safety = self._calc_safety_score(token)
        timing = self._calc_timing_score(token)
        
        # Weighted average: momentum pesa más (trading es sobre momentum)
        total = (momentum * 0.50) + (safety * 0.30) + (timing * 0.20)
        
        return {
            "momentum": round(momentum, 1),
            "safety": round(safety, 1),
            "timing": round(timing, 1),
            "total": round(total, 1),
        }

    def _calc_momentum_score(self, token: dict) -> float:
        """Score 0-100 basado en volumen, velocidad de compras, cambio de precio."""
        score = 0
        
        # Volumen 5 minutos (peso: 30)
        vol_5m = token.get("volume_5m", 0)
        if vol_5m > 50000: score += 30
        elif vol_5m > 20000: score += 25
        elif vol_5m > 5000: score += 20
        elif vol_5m > 1000: score += 10
        elif vol_5m > 500: score += 5

        # Ratio compras/ventas 5min (peso: 25)
        buys = token.get("txns_buys_5m", 0)
        sells = token.get("txns_sells_5m", 0)
        if buys + sells > 0:
            buy_ratio = buys / (buys + sells)
            if buy_ratio > 0.75: score += 25
            elif buy_ratio > 0.65: score += 20
            elif buy_ratio > 0.55: score += 15
            elif buy_ratio > 0.50: score += 10

        # Cambio de precio 5min (peso: 25)
        chg_5m = token.get("price_change_5m", 0)
        if chg_5m > 50: score += 25
        elif chg_5m > 20: score += 22
        elif chg_5m > 10: score += 18
        elif chg_5m > 5: score += 12
        elif chg_5m > 0: score += 5
        elif chg_5m < -10: score -= 10

        # Volumen 1h relativo a market cap (peso: 20)
        vol_1h = token.get("volume_1h", 0)
        mc = token.get("market_cap", 0) or token.get("fdv", 1)
        if mc > 0:
            vol_mc_ratio = vol_1h / mc
            if vol_mc_ratio > 1.0: score += 20   # Volumen > market cap = hype extremo
            elif vol_mc_ratio > 0.5: score += 18
            elif vol_mc_ratio > 0.2: score += 14
            elif vol_mc_ratio > 0.1: score += 10
            elif vol_mc_ratio > 0.05: score += 5

        return max(0, min(100, score))

    def _calc_safety_score(self, token: dict) -> float:
        """Score 0-100 basado en liquidez, distribución, edad."""
        score = 50  # Base neutral

        # Liquidez (peso: 40)
        liq = token.get("liquidity_usd", 0)
        if liq > 100000: score += 30
        elif liq > 50000: score += 25
        elif liq > 20000: score += 18
        elif liq > 10000: score += 10
        elif liq > 5000: score += 5
        elif liq < 2000: score -= 20

        # Edad del token (peso: 30)
        age_min = token.get("age_minutes")
        if age_min is not None:
            if age_min < 5: score -= 15   # Muy nuevo, peligroso
            elif age_min < 15: score -= 5
            elif age_min < 60: score += 5
            elif age_min < 360: score += 10
            elif age_min < 1440: score += 15
            else: score += 5  # Tokens viejos pueden estar muertos

        # Transacciones diversas (peso: 20)
        total_txns = (token.get("txns_buys_1h", 0) + token.get("txns_sells_1h", 0))
        if total_txns > 500: score += 15
        elif total_txns > 100: score += 10
        elif total_txns > 20: score += 5
        elif total_txns < 5: score -= 10

        return max(0, min(100, score))

    def _calc_timing_score(self, token: dict) -> float:
        """Score 0-100 basado en el momento óptimo de entrada."""
        score = 50

        # Cambio de precio reciente (¿estamos en dip o en rally?)
        chg_5m = token.get("price_change_5m", 0)
        chg_1h = token.get("price_change_1h", 0)
        
        # Ideal: Rally reciente moderado (no comprar en pico)
        if 5 < chg_5m < 30 and chg_1h > 0:
            score += 20  # Rally moderado — buen entry
        elif 0 < chg_5m <= 5 and chg_1h > 10:
            score += 25  # Consolidando después de pump — mejor entry
        elif chg_5m > 50:
            score -= 20  # Ya pumpeó demasiado — alto riesgo
        elif chg_5m < -20:
            score -= 15  # Dump activo — peligroso

        # Ratio de volumen reciente (5m vs 1h)
        vol_5m = token.get("volume_5m", 0)
        vol_1h = token.get("volume_1h", 0)
        if vol_1h > 0:
            recent_ratio = (vol_5m * 12) / vol_1h  # Normalizar a 1h equiv
            if 1.5 < recent_ratio < 5.0:
                score += 15  # Volumen acelerando
            elif recent_ratio > 10:
                score -= 10  # Spike sospechoso

        return max(0, min(100, score))

    # ══════════════════════════════════════════════════════════
    #  📋 WATCHLIST SOLANA (Top tokens para dashboard)
    # ══════════════════════════════════════════════════════════

    async def get_watchlist_prices(self) -> list:
        """Precios de los tokens Solana más relevantes para el dashboard."""
        SOLANA_WATCHLIST = [
            {"mint": "So11111111111111111111111111111111111111112",    "symbol": "SOL"},
            {"mint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",  "symbol": "JUP"},
            {"mint": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", "symbol": "WIF"},
            {"mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", "symbol": "BONK"},
            {"mint": "rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof",  "symbol": "RENDER"},
        ]
        try:
            mints = [w["mint"] for w in SOLANA_WATCHLIST]
            ids = ",".join(mints)
            url = f"https://api.jup.ag/price/v2?ids={ids}"
            headers = {"x-api-key": os.getenv("JUPITER_API_KEY", "")} if os.getenv("JUPITER_API_KEY") else {}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status != 200:
                        return SOLANA_WATCHLIST
                    data = await r.json()
                    for w in SOLANA_WATCHLIST:
                        pd = data.get("data", {}).get(w["mint"], {})
                        w["price_usd"] = float(pd.get("price", 0))
                    return SOLANA_WATCHLIST
        except:
            return SOLANA_WATCHLIST
    async def get_ohlcv_data(self, mint: str, timeframe: str = "15m") -> list:
        """
        Obtiene datos históricos reales (Open, High, Low, Close, Volume) para un mint.
        Primero busca el pool más líquido en DexScreener y luego consulta GeckoTerminal.
        """
        if not mint:
            log.warning(f"Búsqueda OHLCV abortada: mint vacío")
            return []

        # 1. Resolver pool_address (pairAddress)
        pool_address = self._pool_address_cache.get(mint)
        log.info(f"Iniciando búsqueda OHLCV para {mint} (Pool pre-caché: {pool_address})")
        
        try:
            async with aiohttp.ClientSession() as session:
                if not pool_address:
                    url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                        if r.status == 200:
                            data = await r.json()
                            pairs = data.get("pairs", [])
                            log.info(f"DexScreener encontró {len(pairs)} pares para {mint}")
                            if pairs:
                                # Usar el par más líquido de Solana
                                sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
                                if sol_pairs:
                                    sol_pairs.sort(key=lambda x: float(x.get("liquidity", {}).get("usd", 0) or 0), reverse=True)
                                    pool_address = sol_pairs[0].get("pairAddress")
                                    log.info(f"Pool seleccionado: {pool_address}")
                                    self._pool_address_cache[mint] = pool_address
                        else:
                            log.warning(f"DexScreener error {r.status} para {mint}")

                if not pool_address:
                    log.warning(f"No se encontró pool para {mint}")
                    return []

                # 2. Consultar GeckoTerminal para OHLCV
                # GeckoTerminal: minute (1, 5, 15), hour (1, 4, 12), day (1)
                res = 15 # default 15m
                gt_tf = "minute"
                
                clean_tf = timeframe.lower()
                if "1m" == clean_tf: res = 1; gt_tf = "minute"
                elif "5m" == clean_tf: res = 5; gt_tf = "minute"
                elif "15m" == clean_tf: res = 15; gt_tf = "minute"
                elif "1h" == clean_tf: res = 1; gt_tf = "hour"
                elif "4h" == clean_tf: res = 4; gt_tf = "hour"
                elif "1d" == clean_tf: res = 1; gt_tf = "day"
                
                url_gt = f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool_address}/ohlcv/{gt_tf}?aggregate={res}&limit=100"
                log.info(f"Fetch GeckoTerminal: {url_gt}")
                
                headers = {
                    "accept": "application/json",
                    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                async with session.get(url_gt, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status != 200:
                        log.warning(f"GeckoTerminal error {r.status} para {pool_address}")
                        return []
                    
                    data = await r.json()
                    ohlcv_list = data.get("data", {}).get("attributes", {}).get("ohlcv_list", [])
                    
                    # GeckoTerminal retorna [timestamp, open, high, low, close, volume]
                    # Formatear para Lightweight Charts
                    formatted = []
                    for b in ohlcv_list:
                        formatted.append({
                            "time": b[0],
                            "open": float(b[1]),
                            "high": float(b[2]),
                            "low": float(b[3]),
                            "close": float(b[4]),
                            "volume": float(b[5])
                        })
                    
                    # Ordenar cronológicamente (GT suele enviar del más reciente al más antiguo)
                    formatted.sort(key=lambda x: x["time"])
                    return formatted

        except Exception as e:
            log.error(f"Error fetching OHLCV for {mint}: {e}")
            return []

    def get_mint_by_symbol(self, symbol: str) -> str:
        """Busca el mint asociado a un símbolo en la lista de bluechips o en caché."""
        clean_sym = symbol.replace("USDC", "").replace("/", "").upper()
        
        # 1. Buscar en Bluechips
        for bc in SOLANA_BLUECHIPS:
            if bc["symbol"].upper() == clean_sym:
                return bc["mint"]
        
        # 2. Fallback: Mapeo común (en caso de que no esté en bluechips)
        common = {
            "SOL": "So11111111111111111111111111111111111111112",
            "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        }
        return common.get(clean_sym)

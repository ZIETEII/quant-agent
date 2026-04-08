"""
╔══════════════════════════════════════════════════════════╗
║   JUPITER CLIENT — Exchange Abstraction Layer            ║
║   Soporta: Paper Trading (simulación) + Live Trading     ║
║   Blockchain: Solana · DEX: Jupiter v6 / Raydium         ║
╚══════════════════════════════════════════════════════════╝
"""

import os
import time
import logging
import aiohttp
import asyncio
import json
from datetime import datetime

log = logging.getLogger("AgenteBot.Exchange")

# ── SOL mint address (used as base currency) ──
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

class JupiterClient:
    """
    Abstracción del exchange para trading de tokens Solana.
    En PAPER_MODE simula swaps usando precios reales de Jupiter.
    En LIVE_MODE ejecuta swaps reales via Jupiter v6 API.
    """

    def __init__(self, paper_mode=True):
        self.paper_mode = paper_mode
        self.wallet_address = os.getenv("SOLANA_WALLET_ADDRESS", "")
        self.rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
        
        
        # Paper trading state
        self.paper_balance_usd = float(os.getenv("VIRTUAL_BALANCE_USD", "1000.0"))
        self.paper_holdings = {}  # {token_address: {"qty": float, "avg_entry": float}}
        
        # Price cache
        self._price_cache = {}  # {mint: {"price": float, "ts": float}}
        self._price_cache_ttl = 5  # seconds
        
        log.info(f"JupiterClient initialized | Mode: {'PAPER' if paper_mode else 'LIVE'} | Balance: ${self.paper_balance_usd:.2f} USDC")

    # ══════════════════════════════════════════════════════════
    #  💰 BALANCE
    # ══════════════════════════════════════════════════════════

    def get_sol_balance(self) -> float:
        """Retorna el balance en SOL (paper o real)."""
        if self.paper_mode or "devnet" in self.rpc_url.lower():
            # Devnet liquidity mapping for seamless testing
            return self.paper_balance_usd  # Return as generic balance
            
        # LIVE MAINNET QUERY
        import requests
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [self.wallet_address]}
            resp = requests.post(self.rpc_url, json=payload, timeout=3)
            lamports = resp.json().get("result", {}).get("value", 0)
            return lamports / 1e9
        except Exception as e:
            log.error(f"[RPC] Balance error: {e}")
            return 0.0

    def get_holdings(self) -> dict:
        """Retorna las posiciones actuales en tokens."""
        if self.paper_mode or "devnet" in self.rpc_url.lower():
            return dict(self.paper_holdings)
        return {}

    async def sync_live_holdings(self) -> dict:
        """Escanea la wallet buscando posiciones abiertas en mainnet para recuperación (Graceful Recovery)."""
        if self.paper_mode or "devnet" in self.rpc_url.lower():
            return self.paper_holdings
            
        try:
            from solana.rpc.async_api import AsyncClient
            from solders.pubkey import Pubkey
        except ImportError:
            log.error("Faltan dependencias (solana-py/solders) para sync_live_holdings")
            return {}

        log.info("[RECOVERY] Buscando posiciones huérfanas en la blockchain...")
        wallet_pubkey = Pubkey.from_string(self.wallet_address)
        holdings = {}
        
        try:
            async with AsyncClient(self.rpc_url) as client:
                # SPL Token Program ID
                TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
                from solana.rpc.types import TokenAccountOpts
                # Get all token accounts by programId
                resp = await client.get_token_accounts_by_owner_json_parsed(
                    wallet_pubkey, 
                    TokenAccountOpts(program_id=TOKEN_PROGRAM_ID)
                )
                
                if getattr(resp, "value", None):
                    for account_info in resp.value:
                        data = account_info.account.data
                        if hasattr(data, "parsed"):
                            info = data.parsed.get("info", {})
                            mint = info.get("mint")
                            
                            # Ignorar USDC
                            if mint in [USDC_MINT, SOL_MINT]:
                                continue
                                
                            token_amount = info.get("tokenAmount", {})
                            amount_ui = float(token_amount.get("uiAmount", 0) or 0)
                            
                            if amount_ui > 0:
                                holdings[mint] = {
                                    "qty": amount_ui,
                                    "atomic": token_amount.get("amount", "0"),
                                    "decimals": token_amount.get("decimals", 0)
                                }
                                
        except Exception as e:
            log.error(f"[RECOVERY ERROR] No se pudo escanear la wallet en mainnet: {e}")
            
        log.info(f"[RECOVERY] Se encontraron {len(holdings)} tokens distintos en la wallet.")
        return holdings

    def get_total_equity_sol(self, live_prices: dict) -> float:
        """Calcula el equity total: SOL libre + valor de tokens en SOL."""
        equity = self.get_sol_balance()
        for mint, holding in self.paper_holdings.items():
            price_sol = live_prices.get(mint, holding.get("avg_entry", 0))
            equity += holding["qty"] * price_sol
        return equity

    # ══════════════════════════════════════════════════════════
    #  📊 PRECIOS (Jupiter Price API)
    # ══════════════════════════════════════════════════════════

    async def get_token_price_sol(self, token_mint: str) -> float:
        """Obtiene el precio de un token en SOL usando Jupiter Price API."""
        cached = self._price_cache.get(token_mint)
        if cached and (time.time() - cached["ts"]) < self._price_cache_ttl:
            return cached["price"]

        try:
            url = f"https://api.jup.ag/price/v2?ids={token_mint}&vsToken={SOL_MINT}"
            headers = {"x-api-key": os.getenv("JUPITER_API_KEY", "")} if os.getenv("JUPITER_API_KEY") else {}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status != 200:
                        return cached["price"] if cached else 0.0
                    data = await r.json()
                    price_data = data.get("data", {}).get(token_mint, {})
                    price = float(price_data.get("price", 0))
                    
                    self._price_cache[token_mint] = {"price": price, "ts": time.time()}
                    return price
        except Exception as e:
            log.warning(f"Price fetch error for {token_mint[:8]}...: {e}")
            return cached["price"] if cached else 0.0

    async def get_token_price_usd(self, token_mint: str) -> float:
        """Precio en USD via Jupiter, con fallback a DexScreener."""
        # SOL nativo: usar método dedicado
        if token_mint == SOL_MINT:
            return await self.get_sol_price_usd()

        cached = self._price_cache.get(f"usd_{token_mint}")
        if cached and (time.time() - cached["ts"]) < self._price_cache_ttl:
            return cached["price"]

        try:
            url = f"https://api.jup.ag/price/v2?ids={token_mint}"
            headers = {"x-api-key": os.getenv("JUPITER_API_KEY", "")} if os.getenv("JUPITER_API_KEY") else {}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 200:
                        data = await r.json()
                        price_data = data.get("data", {}).get(token_mint, {})
                        price = float(price_data.get("price", 0))
                        if price > 0:
                            self._price_cache[f"usd_{token_mint}"] = {"price": price, "ts": time.time()}
                            return price
        except:
            pass

        # Fallback: DexScreener
        try:
            url = f"https://api.dexscreener.com/tokens/v1/solana/{token_mint}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 200:
                        pairs = await r.json()
                        if isinstance(pairs, list) and len(pairs) > 0:
                            price = float(pairs[0].get("priceUsd", 0) or 0)
                            if price > 0:
                                self._price_cache[f"usd_{token_mint}"] = {"price": price, "ts": time.time()}
                                return price
        except:
            pass

        return cached["price"] if cached else 0.0

    async def get_sol_price_usd(self) -> float:
        """Precio actual de SOL en USD via CoinGecko + DexScreener fallback."""
        cached = self._price_cache.get("sol_usd")
        if cached and (time.time() - cached["ts"]) < 30:  # Cache 30s para SOL
            return cached["price"]

        # Método 1: CoinGecko (simple, fiable)
        try:
            url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                    if r.status == 200:
                        data = await r.json()
                        price = float(data.get("solana", {}).get("usd", 0))
                        if price > 0:
                            self._price_cache["sol_usd"] = {"price": price, "ts": time.time()}
                            return price
        except:
            pass

        # Método 2: DexScreener (SOL/USDC pair en Raydium)
        try:
            url = "https://api.dexscreener.com/tokens/v1/solana/So11111111111111111111111111111111111111112"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                    if r.status == 200:
                        pairs = await r.json()
                        if isinstance(pairs, list) and len(pairs) > 0:
                            price = float(pairs[0].get("priceUsd", 0) or 0)
                            if price > 0:
                                self._price_cache["sol_usd"] = {"price": price, "ts": time.time()}
                                return price
        except:
            pass

        # Método 3: Fallback estático (actualizar periódicamente)
        return cached["price"] if cached else 140.0  # Fallback ~$140

    async def get_batch_prices_usd(self, mints: list) -> dict:
        """Obtiene precios USD de múltiples tokens en un solo request usando DexScreener (Mayor liquidez)."""
        if not mints:
            return {}
        try:
            result = {}
            best_liquidity = {} # {mint: liquidity_usd}
            
            for i in range(0, len(mints), 30):
                chunk = mints[i:i+30]
                ids = ",".join(chunk)
                url = f"https://api.dexscreener.com/latest/dex/tokens/{ids}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                        if r.status == 200:
                            data = await r.json()
                            if "pairs" in data and data["pairs"]:
                                for pair in data["pairs"]:
                                    base_addr = pair.get("baseToken", {}).get("address")
                                    quote_addr = pair.get("quoteToken", {}).get("address")
                                    price = float(pair.get("priceUsd", 0))
                                    liq = float(pair.get("liquidity", {}).get("usd", 0))
                                    
                                    if base_addr in chunk and price > 0:
                                        if liq >= best_liquidity.get(base_addr, -1):
                                            result[base_addr] = price
                                            best_liquidity[base_addr] = liq
                                            
                                    elif quote_addr in chunk and price > 0:
                                        if liq >= best_liquidity.get(quote_addr, -1):
                                            result[quote_addr] = price
                                            best_liquidity[quote_addr] = liq
            return result
        except Exception as e:
            log.warning(f"Batch price error: {e}")
            return {}

    # ══════════════════════════════════════════════════════════
    #  🔄 SWAP — COMPRA (SOL → Token)
    # ══════════════════════════════════════════════════════════

    async def swap_buy(self, token_mint: str, amount: float, slippage_bps: int = 2000) -> dict:
        """Compra un token con USDC (paper) o SOL (live)."""
        if self.paper_mode or "devnet" in self.rpc_url.lower():
            return await self._paper_buy(token_mint, amount, slippage_bps)
        else:
            return await self._live_buy(token_mint, amount, slippage_bps)

    async def _paper_buy(self, token_mint: str, usd_amount: float, slippage_bps: int) -> dict:
        """Simulación de compra usando base en USDC reales."""
        if usd_amount > self.paper_balance_usd:
            return {"success": False, "error": f"Insufficient USDC: have {self.paper_balance_usd:.2f}, need {usd_amount:.2f}"}

        price_usd = await self.get_token_price_usd(token_mint)
        sol_usd = await self.get_sol_price_usd()
        
        if price_usd <= 0:
            return {"success": False, "error": "Could not fetch price"}

        qty = usd_amount / price_usd

        # Simulate slippage (use half the max slippage as average)
        effective_slippage = (slippage_bps / 10000) * 0.3  # ~30% of max slippage avg
        qty *= (1 - effective_slippage)

        # Deduct USDC purely for the token
        self.paper_balance_usd -= usd_amount
        
        # Deduct SOL purely for network gas fee
        gas_fee_sol = 0.00005
        if hasattr(self, 'paper_balance_sol_gas'):
            self.paper_balance_sol_gas -= gas_fee_sol

        # Add to holdings
        if token_mint in self.paper_holdings:
            old = self.paper_holdings[token_mint]
            total_qty = old["qty"] + qty
            avg_entry = ((old["qty"] * old["avg_entry_usd"]) + (qty * price_usd)) / total_qty
            self.paper_holdings[token_mint] = {
                "qty": total_qty,
                "avg_entry_usd": avg_entry,
                "avg_entry_sol": avg_entry / sol_usd if sol_usd > 0 else 0,
            }
        else:
            self.paper_holdings[token_mint] = {
                "qty": qty,
                "avg_entry_usd": price_usd,
                "avg_entry_sol": price_usd / sol_usd if sol_usd > 0 else 0,
            }

        log.info(f"[PAPER BUY] {token_mint[:8]}... | {qty:.4f} tokens @ ${price_usd:.8f} | Cost: ${usd_amount:.2f} | Gas: {gas_fee_sol} SOL")
        return {
            "success": True,
            "qty": qty,
            "price_usd": price_usd,
            "price_sol": price_usd / sol_usd if sol_usd > 0 else 0,
            "usd_spent": usd_amount,
            "gas_fee_sol": gas_fee_sol,
            "tx_hash": f"PAPER_{int(time.time()*1000)}",
        }

    async def _get_jupiter_swap_tx(self, input_mint: str, output_mint: str, amount_lamports: int, slippage_bps: int) -> dict:
        """Helper para cotizar y generar la transaccion de swap en Jupiter."""
        if not self.wallet_address:
            return {"success": False, "error": "No wallet address configured"}

        try:
            # 1. Cotizar (Quote)
            url_quote = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount_lamports}&slippageBps={slippage_bps}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url_quote) as r:
                    if r.status != 200:
                        return {"success": False, "error": f"Quote API error: {await r.text()}"}
                    quote_response = await r.json()

            # 2. Swap
            url_swap = "https://quote-api.jup.ag/v6/swap"
            payload = {
                "quoteResponse": quote_response,
                "userPublicKey": self.wallet_address,
                "wrapAndUnwrapSol": True,
                "dynamicComputeUnitLimit": True,
                "prioritizationFeeLamports": "auto"
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(url_swap, json=payload) as r:
                    if r.status != 200:
                        return {"success": False, "error": f"Swap API error: {await r.text()}"}
                    swap_data = await r.json()
            
            swap_tx_b64 = swap_data.get("swapTransaction")
            if not swap_tx_b64:
                return {"success": False, "error": "No swapTransaction returned"}

            return {"success": True, "swap_tx_b64": swap_tx_b64, "quote": quote_response}

        except Exception as e:
            return {"success": False, "error": f"Jupiter Request Exception: {str(e)}"}

    async def _execute_tx(self, swap_tx_b64: str) -> dict:
        """Firma y envia la transaccion usando solders y solana-py"""
        import base64
        try:
            import base58
            from solders.keypair import Keypair
            from solders.transaction import VersionedTransaction
            from solana.rpc.async_api import AsyncClient
        except ImportError:
            return {"success": False, "error": "Faltan instalar dependencias (solana, solders, base58)"}
            
        try:
            pk_b58 = os.getenv("SOLANA_PRIVATE_KEY", "")
            if not pk_b58:
                return {"success": False, "error": "SOLANA_PRIVATE_KEY is missing"}
                
            keypair = Keypair.from_base58_string(pk_b58)
            
            # Deserializar transaccion cruda desde Jupiter (base64)
            raw_tx = base64.b64decode(swap_tx_b64)
            tx = VersionedTransaction.from_bytes(raw_tx)
            
            # Firmar el mensaje con nuestra clave
            signed_tx = VersionedTransaction(tx.message, [keypair])
            
            # Enviar a mainnet
            async with AsyncClient(self.rpc_url) as client:
                resp = await client.send_raw_transaction(bytes(signed_tx))
                # solana-py async send_raw_transaction returns a generic RPCResponse which contains "value" with signature
                sig = getattr(resp, "value", str(resp))
                return {"success": True, "tx_hash": str(sig)}
                
        except Exception as e:
            return {"success": False, "error": f"Sign/Send TX Error: {str(e)}"}

    async def _live_buy(self, token_mint: str, sol_amount: float, slippage_bps: int) -> dict:
        """Ejecución real de compra (SOL a Token) via Jupiter."""
        # Convertir SOL a lamports (9 decimals)
        lamports = int(sol_amount * 1_000_000_000)
        
        log.info(f"[LIVE BUY INICIO] Request {sol_amount} SOL to {token_mint[:8]}...")
        
        swap_res = await self._get_jupiter_swap_tx(
            input_mint=SOL_MINT, 
            output_mint=token_mint, 
            amount_lamports=lamports, 
            slippage_bps=slippage_bps
        )
        
        if not swap_res.get("success"):
            return swap_res
            
        quote = swap_res.get("quote", {})
        tx_res = await self._execute_tx(swap_res["swap_tx_b64"])
        
        if tx_res.get("success"):
            expected_outAmount = int(quote.get("outAmount", 0))
            # Necesitamos inferir los decimales reales del token o guardarlo como float estimado
            price_usd = await self.get_token_price_usd(token_mint) # Guardar referencia de precio
            
            # Estimación de cantidad recibida basada en el precio
            sol_price_usd = await self.get_sol_price_usd()
            usd_spent = sol_amount * sol_price_usd
            estimated_qty = (usd_spent / price_usd) * 0.95 if price_usd > 0 else 0

            # Descontar del balance de la aplicación para que la UI no sume doble
            self.paper_balance_usd -= usd_spent

            log.info(f"[LIVE BUY ÉXITO] Hash: {tx_res.get('tx_hash')}")
            return {
                "success": True,
                "tx_hash": tx_res.get("tx_hash"),
                "sol_spent": sol_amount,
                "usd_spent": usd_spent,
                "price_usd": price_usd,
                "qty": estimated_qty,
                "msg": "Transaction broadcasted successfully (Check Explorer)"
            }
        else:
            log.error(f"[LIVE BUY ERROR] {tx_res.get('error')}")
            return tx_res

    # ══════════════════════════════════════════════════════════
    #  🔄 SWAP — VENTA (Token → SOL)
    # ══════════════════════════════════════════════════════════

    async def swap_sell(self, token_mint: str, qty: float = None, sell_pct: float = 1.0, slippage_bps: int = 2000) -> dict:
        """
        Vende un token a SOL.
        qty: cantidad exacta a vender. Si None, usa sell_pct del holding.
        sell_pct: fracción a vender (1.0 = 100%, 0.8 = 80% para moonbag).
        """
        if self.paper_mode or "devnet" in self.rpc_url.lower():
            return await self._paper_sell(token_mint, qty, sell_pct, slippage_bps)
        else:
            return await self._live_sell(token_mint, qty, sell_pct, slippage_bps)

    async def _paper_sell(self, token_mint: str, qty: float, sell_pct: float, slippage_bps: int) -> dict:
        """Simulación de venta usando precios reales."""
        holding = self.paper_holdings.get(token_mint)
        if not holding or holding["qty"] <= 0:
            return {"success": False, "error": "No holdings for this token"}

        sell_qty = qty if qty else holding["qty"] * sell_pct

        if sell_qty > holding["qty"]:
            sell_qty = holding["qty"]

        price_usd = await self.get_token_price_usd(token_mint)
        sol_usd = await self.get_sol_price_usd()

        if price_usd <= 0:
            return {"success": False, "error": "Could not fetch price"}

        usd_received = sell_qty * price_usd

        # Simulate slippage
        effective_slippage = (slippage_bps / 10000) * 0.3
        usd_received *= (1 - effective_slippage)

        gas_fee_sol = 0.00005
        if hasattr(self, 'paper_balance_sol_gas'):
            self.paper_balance_sol_gas -= gas_fee_sol

        # Calculate PnL
        entry_usd = holding["avg_entry_usd"]
        pnl_usd = (price_usd - entry_usd) * sell_qty
        pnl_pct = ((price_usd - entry_usd) / entry_usd * 100) if entry_usd > 0 else 0

        # Update holdings
        holding["qty"] -= sell_qty
        if holding["qty"] < 0.0001:
            del self.paper_holdings[token_mint]

        # Adicionar USD devuelto al balance base
        self.paper_balance_usd += usd_received

        log.info(f"[PAPER SELL] {token_mint[:8]}... | {sell_qty:.4f} tokens @ ${price_usd:.8f} | Got: ${usd_received:.2f} USDC | PnL: ${pnl_usd:+.4f} ({pnl_pct:+.2f}%)")
        return {
            "success": True,
            "qty_sold": sell_qty,
            "price_usd": price_usd,
            "usd_received": usd_received,
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "gas_fee_sol": gas_fee_sol,
            "tx_hash": f"PAPER_{int(time.time()*1000)}",
        }

    async def _live_sell(self, token_mint: str, qty: float, sell_pct: float, slippage_bps: int) -> dict:
        """Ejecución real de venta (Token a SOL) via Jupiter, consultando el balance del token on-chain."""
        
        log.info(f"[LIVE SELL INICIO] Evaluando token {token_mint[:8]}... (Sell Pct: {sell_pct*100}%)")
        
        try:
            from solana.rpc.async_api import AsyncClient
            from solana.rpc.types import TokenAccountOpts
            from solders.pubkey import Pubkey
        except ImportError:
            return {"success": False, "error": "Faltan dependencias (solana-py)"}

        # 1. 🔍 Leer Balance de tu Wallet directamente de la red para ese Token
        wallet_pubkey = Pubkey.from_string(self.wallet_address)
        mint_pubkey = Pubkey.from_string(token_mint)
        
        atomic_amount_str = "0"
        try:
            async with AsyncClient(self.rpc_url) as client:
                resp = await client.get_token_accounts_by_owner_json_parsed(
                    wallet_pubkey, 
                    TokenAccountOpts(mint=mint_pubkey)
                )
                
                # Acceder al resultado RPC parseado (JSON)
                if getattr(resp, "value", None) and len(resp.value) > 0:
                    account_data = resp.value[0].account.data
                    if hasattr(account_data, "parsed"):
                        info = account_data.parsed.get("info", {})
                        atomic_amount_str = info.get("tokenAmount", {}).get("amount", "0")
                        
        except Exception as e:
            return {"success": False, "error": f"Error leyendo balance on-chain de Solana RPC: {str(e)}"}
            
        atomic_balance = int(atomic_amount_str)
        if atomic_balance <= 0:
             return {"success": False, "error": "Balance insuficiente (On-Chain el bot detectó 0)"}

        # 2. 🧮 Calcular la fracción a vender de forma atómica exactas (sin float)
        sell_amount_lamports = int(atomic_balance * sell_pct)
        if sell_amount_lamports <= 0:
            return {"success": False, "error": "Monto atómico resultante a vender es 0"}

        # 3. 🪙 Pedir Quote a Jupiter (Token -> SOL)
        swap_res = await self._get_jupiter_swap_tx(
            input_mint=token_mint, 
            output_mint=SOL_MINT, 
            amount_lamports=sell_amount_lamports, 
            slippage_bps=slippage_bps
        )
        
        if not swap_res.get("success"):
            return swap_res
            
        # 4. ✍️ Firmar e inyectar la Transacción a Solana
        tx_res = await self._execute_tx(swap_res["swap_tx_b64"])
        
        if tx_res.get("success"):
            price_usd = await self.get_token_price_usd(token_mint) # Guardamos para métricas/BD
            
            # Estimación de recibo en vivo (outAmount son lamports recibidos)
            expected_outAmount = int(swap_res.get("quote", {}).get("outAmount", 0))
            sol_price_usd = await self.get_sol_price_usd()
            usd_received = (expected_outAmount / 1_000_000_000) * sol_price_usd
            
            # Reintegrar al balance de la aplicación
            self.paper_balance_usd += usd_received
            
            log.info(f"[LIVE SELL ÉXITO] 🎉 Hash: {tx_res.get('tx_hash')}")
            return {
                "success": True,
                "tx_hash": tx_res.get("tx_hash"),
                "price_usd": price_usd,
                "usd_received": usd_received,
                "msg": "Transacción de venta enviada correctamente al DEX"
            }
        else:
            log.error(f"[LIVE SELL ERROR] {tx_res.get('error')}")
            return tx_res

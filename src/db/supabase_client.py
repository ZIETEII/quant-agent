"""
supabase_client.py — Cliente Supabase para el bot Quant Agent
Conecta al Supabase self-hosted en el VPS vía logvoxNet (http://kong:8000)
"""
import os
import logging
import aiohttp
import asyncio
from typing import Optional, Dict, Any

log = logging.getLogger("AgenteBot.Supabase")

SUPABASE_URL        = os.getenv("SUPABASE_URL", "http://kong:8000")
SUPABASE_ANON_KEY   = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# ── Headers base ──
def _anon_headers() -> Dict[str, str]:
    return {
        "apikey":        SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type":  "application/json",
    }

def _service_headers() -> Dict[str, str]:
    return {
        "apikey":        SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type":  "application/json",
    }

def _user_headers(access_token: str) -> Dict[str, str]:
    return {
        "apikey":        SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {access_token}",
        "Content-Type":  "application/json",
    }


# ══════════════════════════════════════════════════════════
#  🔐 AUTH
# ══════════════════════════════════════════════════════════

async def sign_in(email: str, password: str) -> Dict[str, Any]:
    """
    Login con email + contraseña.
    Retorna: {"access_token": ..., "user": {...}, "error": None}
    """
    url = f"{SUPABASE_URL}/auth/v1/token?grant_type=password"
    payload = {"email": email, "password": password}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=_anon_headers(), timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()

                if resp.status != 200:
                    error_msg = data.get("error_description") or data.get("msg") or "Login fallido"
                    log.warning(f"[Auth] Login fallido para {email}: {error_msg}")
                    return {"access_token": None, "user": None, "error": error_msg}

                log.info(f"[Auth] Login exitoso: {email}")
                return {
                    "access_token":  data.get("access_token"),
                    "refresh_token": data.get("refresh_token"),
                    "expires_in":    data.get("expires_in"),
                    "user":          data.get("user"),
                    "error":         None,
                }
    except Exception as e:
        log.error(f"[Auth] Error en sign_in: {e}")
        return {"access_token": None, "user": None, "error": str(e)}


async def sign_out(access_token: str) -> bool:
    """Invalida el token en Supabase Auth."""
    url = f"{SUPABASE_URL}/auth/v1/logout"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=_user_headers(access_token), timeout=aiohttp.ClientTimeout(total=8)) as resp:
                return resp.status in (200, 204)
    except Exception as e:
        log.error(f"[Auth] Error en sign_out: {e}")
        return False


async def get_user(access_token: str) -> Optional[Dict[str, Any]]:
    """Verifica y retorna el usuario del token JWT."""
    url = f"{SUPABASE_URL}/auth/v1/user"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=_user_headers(access_token), timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
    except Exception as e:
        log.error(f"[Auth] Error en get_user: {e}")
        return None


async def refresh_token(refresh_tok: str) -> Optional[Dict[str, Any]]:
    """Renueva el access_token usando el refresh_token."""
    url = f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"refresh_token": refresh_tok},
                headers=_anon_headers(),
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
    except Exception as e:
        log.error(f"[Auth] Error en refresh_token: {e}")
        return None


# ══════════════════════════════════════════════════════════
#  👤 PROFILE
# ══════════════════════════════════════════════════════════

async def get_profile(access_token: str) -> Optional[Dict[str, Any]]:
    """
    Obtiene el perfil del usuario autenticado desde public.profiles.
    Usa el access_token del usuario (RLS: solo ve su propio perfil).
    """
    url = f"{SUPABASE_URL}/rest/v1/profiles?select=*"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=_user_headers(access_token), timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    rows = await resp.json()
                    return rows[0] if rows else None
                return None
    except Exception as e:
        log.error(f"[Profile] Error en get_profile: {e}")
        return None


async def get_profile_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Obtiene perfil por user_id usando service key (para uso interno del bot/admin).
    """
    url = f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}&select=*"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=_service_headers(), timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    rows = await resp.json()
                    return rows[0] if rows else None
                return None
    except Exception as e:
        log.error(f"[Profile] Error en get_profile_by_id: {e}")
        return None


async def list_all_profiles() -> list:
    """Lista todos los perfiles (solo admin / service key)."""
    url = f"{SUPABASE_URL}/rest/v1/profiles?select=id,username,display_name,virtual_balance,is_admin,is_active,created_at"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=_service_headers(), timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    return await resp.json()
                return []
    except Exception as e:
        log.error(f"[Profile] Error en list_all_profiles: {e}")
        return []


async def update_profile(access_token: str, data: Dict[str, Any]) -> bool:
    """Actualiza campos del perfil del usuario autenticado."""
    url = f"{SUPABASE_URL}/rest/v1/profiles"
    headers = {**_user_headers(access_token), "Prefer": "return=minimal"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.patch(url, json=data, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                return resp.status in (200, 204)
    except Exception as e:
        log.error(f"[Profile] Error en update_profile: {e}")
        return False


# ══════════════════════════════════════════════════════════
#  💰 FONDOS
# ══════════════════════════════════════════════════════════

async def add_funds(user_id: str, amount: float, note: str = "Depósito manual") -> Optional[Dict]:
    """
    Agrega fondos virtuales al usuario.
    Llama a la función PostgreSQL add_funds() via RPC.
    Usa service key (operación admin).
    """
    url = f"{SUPABASE_URL}/rest/v1/rpc/add_funds"
    payload = {"p_user_id": user_id, "p_amount": amount, "p_note": note}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=_service_headers(), timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.json()
                error = await resp.text()
                log.error(f"[Funds] add_funds error {resp.status}: {error}")
                return None
    except Exception as e:
        log.error(f"[Funds] Error en add_funds: {e}")
        return None


async def get_fund_history(user_id: str, limit: int = 20) -> list:
    """Historial de transacciones del usuario."""
    url = (
        f"{SUPABASE_URL}/rest/v1/fund_transactions"
        f"?user_id=eq.{user_id}&order=created_at.desc&limit={limit}"
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=_service_headers(), timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    return await resp.json()
                return []
    except Exception as e:
        log.error(f"[Funds] Error en get_fund_history: {e}")
        return []


# ══════════════════════════════════════════════════════════
#  🔧 HEALTH CHECK
# ══════════════════════════════════════════════════════════

async def health_check() -> bool:
    """Verifica que el Supabase VPS esté accesible."""
    url = f"{SUPABASE_URL}/rest/v1/"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=_anon_headers(), timeout=aiohttp.ClientTimeout(total=5)) as resp:
                ok = resp.status in (200, 404)  # 404 = endpoint no existe pero kong responde
                if ok:
                    log.info(f"[Supabase] ✅ VPS accesible en {SUPABASE_URL}")
                else:
                    log.warning(f"[Supabase] ⚠️ Respuesta inesperada: {resp.status}")
                return ok
    except Exception as e:
        log.error(f"[Supabase] ❌ No se puede conectar a {SUPABASE_URL}: {e}")
        return False

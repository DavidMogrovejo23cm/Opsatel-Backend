import os
import re
# pyrefly: ignore [missing-import]
import httpx
import logging
from typing import Optional, Dict, List

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("xui_service")

# Config variables from environment
XUI_URL = os.getenv("XUI_URL", "http://172.30.0.3/bwfdVuGs").rstrip("/")
XUI_USERNAME = os.getenv("XUI_USERNAME", "DAVIDOPSA")
XUI_PASSWORD = os.getenv("XUI_PASSWORD", "OPSATEL.@#22")

# Global HTTP client session to keep cookies
_http_session: Optional[httpx.AsyncClient] = None

def _get_session() -> httpx.AsyncClient:
    global _http_session
    if _http_session is None:
        _http_session = httpx.AsyncClient(
            timeout=20.0,
            verify=False,  # XUI panels might use self-signed certificates
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": f"{XUI_URL}/users",
            },
            follow_redirects=True
        )
    return _http_session

async def do_login() -> None:
    session = _get_session()
    login_url = f"{XUI_URL}/login"
    logger.info(f"🔐 XUI: Iniciando login en dos pasos en {login_url}...")

    # Step 1: GET /login to initialize session cookies and fetch the referrer token
    referrer_val = ""
    try:
        r_get = await session.get(login_url)
        referrer_match = re.search(r'name="referrer"\s+value="([^"]*)"', r_get.text)
        if referrer_match:
            referrer_val = referrer_match.group(1)
    except Exception as e:
        logger.warning(f"XUI: Error en el GET de login inicial: {e}")

    # Step 2: POST /login
    payload = {
        "username": XUI_USERNAME,
        "password": XUI_PASSWORD,
        "referrer": referrer_val,
        "login": "Login",
    }

    try:
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": login_url
        }
        r = await session.post(login_url, data=payload, headers=headers)
        html = r.text
        if "XUI | Login" in html or 'data-id="login"' in html:
            raise ConnectionError("Login en panel XUI.one rechazado. Verifica credenciales.")
        logger.info("✅ XUI: Login de sesión IPTV exitoso.")
    except Exception as e:
        logger.error(f"XUI: Error de login en el panel: {e}")
        raise

async def create_xui_user(
    username: str, 
    password: str, 
    max_connections: int = 1,
    bouquets: str = "[1,2,5]",
    allowed_outputs: str = "[1,2]"
) -> Dict:
    """
    Simulates the XUI.one panel line/user creation request.
    Uses the same HTTP session to preserve authentication.
    """
    session = _get_session()
    
    # Ensure active login session
    cookies = dict(session.cookies)
    if "PHPSESSID" not in cookies:
        await do_login()

    api_url = f"{XUI_URL}/api"
    
    # Form payload for creating a new IPTV line in XUI.one
    payload = {
        "action": "user_new",  # Default action in XUI.one for creating users
        "username": username,
        "password": password,
        "member_id": 1,
        "bouquet": bouquets,
        "allowed_outputs": allowed_outputs,
        "max_connections": max_connections,
        "admin_enabled": 1,
        "enabled": 1,
        "is_restreamer": 0,
        "is_trial": 0,
        "is_mag": 0,
        "is_e2": 0,
        "is_stalker": 0,
        "is_isplock": 0,
        "allowed_ips": "[]",
        "allowed_ua": "[]",
        "bypass_ua": 0,
        "force_server_id": 0
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": f"{XUI_URL}/users"
    }

    async def _send_create():
        r = await session.post(api_url, data=payload, headers=headers)
        if r.status_code != 200:
            raise ConnectionError(f"HTTP {r.status_code} al crear usuario en XUI")
        
        # Check if login expired and we got redirected to login page
        if "XUI | Login" in r.text or 'data-id="login"' in r.text:
            raise ConnectionError("Sesión de XUI expirada.")
            
        try:
            return r.json()
        except Exception:
            # Check if successful response HTML or plaintext is returned
            if "success" in r.text.lower() or '"result":1' in r.text or "true" in r.text.lower():
                return {"success": True, "msg": "Usuario creado"}
            raise ConnectionError(f"Respuesta de XUI no parseable: {r.text[:200]}")

    try:
        return await _send_create()
    except ConnectionError as ce:
        if "expirada" in str(ce):
            logger.warning("XUI: Sesión expirada durante creación. Re-autenticando...")
            await do_login()
            return await _send_create()
        raise
    except Exception as e:
        logger.error(f"XUI: Fallo al crear usuario {username}: {e}")
        raise

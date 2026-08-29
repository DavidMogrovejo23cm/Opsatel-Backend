import os
import re
try:
    # pyrefly: ignore [missing-import]
    import httpx
except ImportError:
    httpx = None
import logging
from typing import Optional, Dict, List, Any

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("xui_service")

# Config variables from environment
XUI_URL = os.getenv("XUI_URL", "http://172.30.0.3/bwfdVuGs").rstrip("/")
XUI_USERNAME = os.getenv("XUI_USERNAME", "DAVIDOPSA")
XUI_PASSWORD = os.getenv("XUI_PASSWORD", "OPSATEL.@#22")

# Global HTTP client session to keep cookies
_http_session: Any = None

def _get_session() -> Any:
    global _http_session
    if httpx is None:
        raise ConnectionError("El paquete 'httpx' no está instalado en el entorno. Reconstruye la imagen de Docker o ejecuta 'pip install httpx'.")
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
    bouquets: List[str] = ["1", "2", "5"],
    allowed_outputs: List[str] = ["1", "2"]
) -> Dict:
    """
    Simulates the XUI.one panel line creation request using post.php.
    Uses strict multipart/form-data via the 'files' parameter in httpx.
    """
    session = _get_session()
    
    # Ensure active login session
    cookies = dict(session.cookies)
    if "PHPSESSID" not in cookies:
        await do_login()

    url = f"{XUI_URL}/post.php?action=line&referrer=lines&order=0&dir=desc"
    
    import json
    # XUI.one expects bouquets_selected as a JSON string of strings, e.g. ["1","2","5"]
    bouquets_json = json.dumps([str(b) for b in bouquets], separators=(",", ":"))

    # Construct the form fields for strict multipart/form-data using (None, value)
    files = [
        ("bouquets_selected", (None, bouquets_json)),
        ("username", (None, username)),
        ("password", (None, password)),
        ("member_id", (None, "16")),  # Member ID for your reseller/admin account in XUI
        ("no_expire", (None, "on")),
        ("max_connections", (None, str(max_connections))),
        ("contact", (None, "")),
        ("admin_notes", (None, "")),
        ("reseller_notes", (None, "")),
        ("force_server_id", (None, "0")),
        ("isp_clear", (None, "")),
        ("access_token", (None, "")),
        ("forced_country", (None, ""))
    ]

    # Append list values for outputs (access_output[])
    for out in allowed_outputs:
        files.append(("access_output[]", (None, str(out))))

    headers = {
        "Referer": f"{XUI_URL}/line",
        "Origin": XUI_URL.split("/bwfdVuGs")[0],
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "*/*"
    }

    async def _send_create():
        # files= parameter forces HTTPX to send as multipart/form-data
        r = await session.post(url, files=files, headers=headers)
        if r.status_code != 200:
            raise ConnectionError(f"HTTP {r.status_code} al crear línea en XUI")
        
        # Check if login expired
        if "XUI | Login" in r.text or 'data-id="login"' in r.text:
            raise ConnectionError("Sesión de XUI expirada.")
            
        try:
            data = r.json()
            # XUI.one success response: {"result":true,"location":"lines?status=1","status":1}
            if data.get("result") is True or data.get("success") is True or str(data.get("status")) == "1":
                logger.info(f"✅ XUI: Línea {username} creada exitosamente en el panel.")
                return {"success": True, "data": data}
            else:
                logger.error(f"❌ XUI: El panel rechazó la creación de la línea {username}. Respuesta: {data}")
                return {"success": False, "data": data}
        except Exception:
            # Fallback text check
            if '"result":true' in r.text.lower() or '"success":true' in r.text.lower() or '"status":1' in r.text:
                logger.info(f"✅ XUI (Fallback Text Match): Línea {username} creada exitosamente.")
                return {"success": True, "msg": "Línea creada"}
            logger.error(f"❌ XUI: Error parseando respuesta o fallo de creación. Raw Response: {r.text[:300]}")
            return {"success": False, "detail": r.text[:200]}

    try:
        return await _send_create()
    except ConnectionError as ce:
        if "expirada" in str(ce):
            logger.warning("XUI: Sesión expirada durante creación. Re-autenticando...")
            await do_login()
            return await _send_create()
        raise
    except Exception as e:
        logger.error(f"XUI: Fallo al crear línea {username}: {e}")
        raise

async def delete_xui_user(username: str) -> Dict:
    """
    Busca el ID de línea para el usuario especificado en XUI.one y lo elimina del panel.
    """
    session = _get_session()
    
    # Asegurar sesión activa de login
    cookies = dict(session.cookies)
    if "PHPSESSID" not in cookies:
        await do_login()
        
    # Buscar el usuario en la lista de líneas para obtener su ID
    search_url = f"{XUI_URL}/lines?search={username}"
    headers = {
        "Referer": f"{XUI_URL}/lines",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    }
    
    try:
        r = await session.get(search_url, headers=headers)
        if "XUI | Login" in r.text or 'data-id="login"' in r.text:
            await do_login()
            r = await session.get(search_url, headers=headers)
            
        html = r.text
        # Buscar el ID de línea en los checkbox o enlaces correspondientes
        # Ej: line?id=123 o checkbox name="list[]" value="123"
        match = re.search(r'line\?id=(\d+)', html)
        if not match:
            match = re.search(r'name="list\[\]"\s+value="(\d+)"', html)
        if not match:
            # Búsqueda genérica alrededor del nombre de usuario
            pattern = rf'value="(\d+)"[^>]*>[^<]*{re.escape(username)}'
            match = re.search(pattern, html, re.IGNORECASE)
            if not match:
                pattern = rf'{re.escape(username)}[^<]*value="(\d+)"'
                match = re.search(pattern, html, re.IGNORECASE)
                
        if not match:
            logger.warning(f"XUI: No se encontró ID de línea para el usuario {username} en la búsqueda.")
            return {"success": False, "detail": "User ID not found in search results"}
            
        line_id = match.group(1)
        logger.info(f"XUI: Encontrado ID de línea {line_id} para {username}. Eliminando...")
        
        # Enviar petición POST para borrar
        delete_url = f"{XUI_URL}/post.php?action=delete&referrer=lines"
        post_data = {
            "list[]": line_id
        }
        headers_post = {
            "Referer": f"{XUI_URL}/lines",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest"
        }
        
        resp = await session.post(delete_url, data=post_data, headers=headers_post)
        logger.info(f"XUI: Respuesta de eliminación para {username} (ID {line_id}): {resp.text[:200]}")
        return {"success": True, "detail": "Línea eliminada exitosamente en XUI"}
        
    except Exception as e:
        logger.error(f"XUI: Error al intentar eliminar el usuario {username}: {e}")
        return {"success": False, "error": str(e)}


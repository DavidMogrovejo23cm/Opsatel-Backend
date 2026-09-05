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
    Busca el ID de línea (user_id) para el usuario especificado en XUI.one y lo elimina del panel.
    Endpoint real del panel XUI: GET /api?action=line&sub=delete&user_id={user_id}
    """
    session = _get_session()
    clean_username = str(username).strip()
    
    if not clean_username:
        return {"success": False, "detail": "Nombre de usuario nulo o vacío"}
        
    # Asegurar sesión activa de login
    cookies = dict(session.cookies)
    if "PHPSESSID" not in cookies:
        await do_login()
        
    line_id = None
    
    # Si la entrada ya es numérica (user_id directo)
    if clean_username.isdigit():
        line_id = clean_username
    else:
        # 1. Búsqueda del usuario mediante el endpoint DataTables de XUI: /table?id=lines
        table_url = f"{XUI_URL}/table"
        params = {
            "id": "lines",
            "draw": "1",
            "start": "0",
            "length": "50",
            "search[value]": clean_username,
            "search[regex]": "false",
            "filter": "reseller"
        }
        headers = {
            "Referer": f"{XUI_URL}/lines?order=0&dir=desc",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest"
        }
        
        try:
            r = await session.get(table_url, params=params, headers=headers)
            if "XUI | Login" in r.text or 'data-id="login"' in r.text:
                await do_login()
                r = await session.get(table_url, params=params, headers=headers)
                
            resp_text = r.text
            
            # Patrones para capturar el user_id numérico de la línea devuelto por DataTables
            patterns = [
                rf'user_id=(\d+)[^>]*>[^<]*{re.escape(clean_username)}',
                rf'{re.escape(clean_username)}[^<]*user_id=(\d+)',
                r'user_id=(\d+)',
                r'line\?id=(\d+)',
                r'data-id=["\']?(\d+)["\']?',
                r'name="list\[\]"\s+value="(\d+)"',
                rf'["\'](\d+)["\'][^\]]*{re.escape(clean_username)}',
                rf'{re.escape(clean_username)}[^\]]*["\'](\d+)["\']'
            ]
            
            for pat in patterns:
                match = re.search(pat, resp_text, re.IGNORECASE)
                if match:
                    line_id = match.group(1)
                    break

            # Si el JSON contiene una estructura 'data', buscar en las filas
            if not line_id:
                try:
                    data_json = r.json()
                    if isinstance(data_json, dict) and "data" in data_json:
                        for row in data_json.get("data", []):
                            row_str = str(row)
                            if clean_username.lower() in row_str.lower():
                                m = re.search(r'(\d+)', row_str)
                                if m:
                                    line_id = m.group(1)
                                    break
                except Exception:
                    pass
                    
        except Exception as table_err:
            logger.warning(f"XUI: Falló búsqueda en /table para {clean_username}: {table_err}")

        # 2. Fallback a la página estática /lines?search= si /table no devolvió resultado
        if not line_id:
            search_url = f"{XUI_URL}/lines?search={clean_username}"
            headers_html = {
                "Referer": f"{XUI_URL}/lines",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            }
            try:
                r_html = await session.get(search_url, headers=headers_html)
                html_text = r_html.text
                patterns_fallback = [
                    r'user_id=(\d+)',
                    r'line\?id=(\d+)',
                    r'data-id=["\']?(\d+)["\']?',
                    r'name="list\[\]"\s+value="(\d+)"'
                ]
                for pat in patterns_fallback:
                    match = re.search(pat, html_text, re.IGNORECASE)
                    if match:
                        line_id = match.group(1)
                        break
            except Exception as lines_err:
                logger.error(f"XUI: Error en fallback /lines para {clean_username}: {lines_err}")

    if not line_id:
        logger.warning(f"XUI: No se encontró ID de línea para el usuario '{clean_username}'.")
        return {"success": False, "detail": f"User ID not found in search results for {clean_username}"}

    logger.info(f"🗑️ XUI: Encontrado user_id {line_id} para '{clean_username}'. Eliminando vía GET API...")
    
    # URL real de eliminación capturada del panel XUI.one:
    # GET http://172.30.0.3/bwfdVuGs/api?action=line&sub=delete&user_id={line_id}
    delete_url = f"{XUI_URL}/api?action=line&sub=delete&user_id={line_id}"
    delete_headers = {
        "Referer": f"{XUI_URL}/lines?order=0&dir=desc",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    async def _send_delete():
        resp = await session.get(delete_url, headers=delete_headers)
        if resp.status_code != 200:
            raise ConnectionError(f"HTTP {resp.status_code} al eliminar usuario en XUI")
            
        if "XUI | Login" in resp.text or 'data-id="login"' in resp.text:
            raise ConnectionError("Sesión de XUI expirada.")
            
        logger.info(f"✅ XUI: Línea {line_id} ({clean_username}) eliminada exitosamente del panel XUI. Respuesta: {resp.text[:200]}")
        return {"success": True, "detail": f"Línea {line_id} ({clean_username}) eliminada exitosamente en XUI", "status_code": resp.status_code}

    try:
        return await _send_delete()
    except ConnectionError as ce:
        if "expirada" in str(ce):
            logger.warning("XUI: Sesión expirada durante eliminación. Re-autenticando...")
            await do_login()
            return await _send_delete()
        raise
    except Exception as e:
        logger.error(f"XUI: Error al eliminar el usuario {clean_username} (ID {line_id}): {e}")
        return {"success": False, "error": str(e)}


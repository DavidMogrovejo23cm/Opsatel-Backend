import requests
from fastapi import APIRouter, Depends, HTTPException

import whatsapp_service
from ..auth import require_role

router = APIRouter()


# --- Estado y control del sistema anti-bloqueo del puente ---

@router.get("/antiban", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def antiban_estado():
    """Estado del gobernador anti-bloqueo (horario, topes, pausas, opt-outs)."""
    try:
        r = requests.get(f"{whatsapp_service.WHATSAPP_BRIDGE_URL.rstrip('/')}/antiban", timeout=5)
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Puente de WhatsApp no disponible: {e}")


@router.post("/antiban/restriccion", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def antiban_declarar_restriccion(horas: float = 24):
    """Declara una restricción de WhatsApp (ej. aviso 'Tu cuenta está restringida'): pausa los envíos masivos X horas
    y reinicia el calentamiento al terminar."""
    try:
        r = requests.post(f"{whatsapp_service.WHATSAPP_BRIDGE_URL.rstrip('/')}/antiban/restricted", json={"hours": horas}, timeout=5)
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Puente de WhatsApp no disponible: {e}")


@router.post("/antiban/reanudar", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def antiban_reanudar():
    """Levanta manualmente la pausa del envío masivo."""
    try:
        r = requests.post(f"{whatsapp_service.WHATSAPP_BRIDGE_URL.rstrip('/')}/antiban/clear", json={}, timeout=5)
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Puente de WhatsApp no disponible: {e}")


@router.post("/logout", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def cerrar_sesion_puente():
    """
    Cierra la sesión activa en el microservicio Node.js (whatsapp-web.js).
    Permite volver a escanear un nuevo código QR.
    """
    provider = whatsapp_service.WHATSAPP_PROVIDER
    if provider != "local-bridge":
        return {"success": True, "message": f"Proveedor {provider} no requiere logout local"}
    
    url = f"{whatsapp_service.WHATSAPP_BRIDGE_URL.rstrip('/')}/logout"
    try:
        resp = requests.post(url, timeout=10)
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo contactar con el puente local para cerrar sesión: {str(e)}")


@router.get("/status-bridge", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def obtener_status_puente():
    """
    Obtiene el estado de conexión del proveedor de WhatsApp activo.
    Para green-api: retorna datos de configuración.
    Para local-bridge: consulta el microservicio Node.js.
    """
    provider = whatsapp_service.WHATSAPP_PROVIDER
    if provider == "green-api":
        instance_id = whatsapp_service.WHATSAPP_INSTANCE_ID
        token = whatsapp_service.WHATSAPP_TOKEN
        if instance_id and token:
            return {
                "status": "GREEN_API",
                "connected": True,
                "provider": "green-api",
                "instance_id": instance_id,
                "message": "Proveedor Green API configurado. Gestiona la sesión en console.green-api.com"
            }
        else:
            return {
                "status": "GREEN_API_NO_CREDENTIALS",
                "connected": False,
                "provider": "green-api",
                "message": "Faltan las variables WHATSAPP_INSTANCE_ID y WHATSAPP_TOKEN en el entorno del servidor."
            }
    return whatsapp_service.get_whatsapp_bridge_status()


@router.get("/qr-bridge", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def obtener_qr_puente():
    """
    Obtiene la imagen Base64 del QR (solo para local-bridge).
    Para green-api, el QR se gestiona en el panel de Green API.
    """
    provider = whatsapp_service.WHATSAPP_PROVIDER
    if provider == "green-api":
        raise HTTPException(
            status_code=400,
            detail="El QR se gestiona en el panel de Green API (console.green-api.com). No aplica para este proveedor."
        )
    res = whatsapp_service.get_whatsapp_bridge_qr()
    if not res.get("qr"):
        raise HTTPException(
            status_code=400,
            detail=res.get("message") or "El código QR no está disponible."
        )
    return res

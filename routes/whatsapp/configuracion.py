from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
import whatsapp_service
from database import get_db
from ..auth import require_role
from .utils import ECUADOR_TZ

router = APIRouter()


def _calcular_proximo_envio(config: models.WhatsAppConfiguracion) -> str:
    try:
        ahora = datetime.now(ECUADOR_TZ)
        hora_partes = config.hora_programada.split(":")
        hora_int = int(hora_partes[0])
        min_int = int(hora_partes[1])
        rec = getattr(config, 'recurrencia', 'diario') or 'diario'
        
        if rec == "diario":
            hora_hoy = ahora.replace(hour=hora_int, minute=min_int, second=0, microsecond=0)
            if ahora < hora_hoy:
                return f"Hoy a las {config.hora_programada}"
            else:
                return f"Mañana a las {config.hora_programada}"
        elif rec == "mensual":
            dia = config.fecha_programada.day if config.fecha_programada else 1
            try:
                fecha_este_mes = ahora.replace(day=dia, hour=hora_int, minute=min_int, second=0, microsecond=0)
            except ValueError:
                fecha_este_mes = ahora.replace(day=28, hour=hora_int, minute=min_int, second=0, microsecond=0)
            
            meses_es = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
            if ahora < fecha_este_mes:
                mes_nombre = meses_es[fecha_este_mes.month - 1]
                return f"{dia} de {mes_nombre} a las {config.hora_programada}"
            else:
                mes_siguiente = ahora.month + 1 if ahora.month < 12 else 1
                mes_nombre = meses_es[mes_siguiente - 1]
                return f"{dia} de {mes_nombre} a las {config.hora_programada}"
        elif rec == "unico":
            if config.fecha_programada:
                return f"{config.fecha_programada.strftime('%Y-%m-%d')} a las {config.hora_programada}"
            return f"A las {config.hora_programada}"
        return f"A las {config.hora_programada}"
    except Exception:
        return f"A las {config.hora_programada}"


# ========================================================================
# CONFIGURACIONES DE ENVÍOS PROGRAMADOS
# ========================================================================

@router.get("/configuraciones", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def listar_configuraciones(db: Session = Depends(get_db)):
    """Obtiene la lista de todas las configuraciones de envíos programados (recurrentes mensuales, diarios y únicos)"""
    try:
        configs = db.query(models.WhatsAppConfiguracion).order_by(
            models.WhatsAppConfiguracion.id.desc()
        ).all()
        
        resultado = []
        for c in configs:
            dia_m = c.fecha_programada.day if c.fecha_programada else 1
            fecha_str = c.fecha_programada.strftime("%Y-%m-%d") if c.fecha_programada else None
            resultado.append({
                "id": c.id,
                "hora": c.hora_programada,
                "mensaje": c.mensaje_programado,
                "activo": c.activo,
                "enviar_a_todos": c.enviar_a_todos,
                "filtro_clientes": getattr(c, 'filtro_clientes', 'todos') or 'todos',
                "nodo": getattr(c, 'nodo', None),
                "recurrencia": getattr(c, 'recurrencia', 'diario') or 'diario',
                "dia_mes": dia_m,
                "fecha": fecha_str,
                "desde_cliente_id": getattr(c, 'desde_cliente_id', None),
                "proximo_envio": _calcular_proximo_envio(c)
            })
        return resultado
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/configuracion", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def obtener_configuracion(db: Session = Depends(get_db)):
    """Obtiene la configuración actual de envío programado"""
    try:
        config = db.query(models.WhatsAppConfiguracion).filter(
            models.WhatsAppConfiguracion.activo == True
        ).first()
        
        if not config:
            return {"configurado": False, "mensaje": "No hay envío programado"}
        
        fecha_str = config.fecha_programada.strftime("%Y-%m-%d") if config.fecha_programada else None
        dia_m = config.fecha_programada.day if config.fecha_programada else 1
        
        return {
            "configurado": True,
            "hora": config.hora_programada,
            "mensaje": config.mensaje_programado,
            "enviar_a_todos": config.enviar_a_todos,
            "filtro_clientes": getattr(config, 'filtro_clientes', 'todos') or 'todos',
            "nodo": getattr(config, 'nodo', None),
            "fecha": fecha_str,
            "dia_mes": dia_m,
            "recurrencia": getattr(config, 'recurrencia', 'diario') or 'diario',
            "desde_cliente_id": getattr(config, 'desde_cliente_id', None),
            "proximo_envio": _calcular_proximo_envio(config),
            "id": config.id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/configuracion/{config_id}/toggle-activo", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def toggle_activo_configuracion(config_id: int, db: Session = Depends(get_db)):
    """Alterna el estado activo/pausado de una configuración de envío programado"""
    try:
        config = db.query(models.WhatsAppConfiguracion).filter(
            models.WhatsAppConfiguracion.id == config_id
        ).first()
        if not config:
            raise HTTPException(status_code=404, detail="Configuración no encontrada")
        config.activo = not config.activo
        db.commit()
        return {
            "success": True,
            "activo": config.activo,
            "message": f"Envío {'activado' if config.activo else 'pausado'} exitosamente"
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/configuracion/{config_id}", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def actualizar_configuracion(
    config_id: int,
    payload: schemas.WhatsAppConfiguracionUpdate,
    db: Session = Depends(get_db)
):
    """Actualiza la configuración de envío programado"""
    try:
        config = db.query(models.WhatsAppConfiguracion).filter(
            models.WhatsAppConfiguracion.id == config_id
        ).first()
        
        if not config:
            raise HTTPException(status_code=404, detail="Configuración no encontrada")
        
        if payload.hora is not None:
            try:
                datetime.strptime(payload.hora, "%H:%M").time()
                config.hora_programada = payload.hora
            except ValueError:
                raise HTTPException(status_code=400, detail="Formato de hora inválido")
        
        if payload.mensaje is not None:
            config.mensaje_programado = payload.mensaje
        
        if payload.activo is not None:
            config.activo = payload.activo
            
        if payload.filtro_clientes is not None:
            config.filtro_clientes = payload.filtro_clientes
            config.enviar_a_todos = (payload.filtro_clientes == "todos")
        elif payload.enviar_a_todos is not None:
            config.enviar_a_todos = payload.enviar_a_todos
            
        if payload.fecha is not None:
            if payload.fecha == "vaciar":
                config.fecha_programada = None
            else:
                try:
                    fecha_obj = datetime.strptime(payload.fecha, "%Y-%m-%d")
                    config.fecha_programada = fecha_obj
                except ValueError:
                    raise HTTPException(status_code=400, detail="Formato de fecha inválido. Use YYYY-MM-DD")
        elif payload.dia_mes is not None and (payload.recurrencia == "mensual" or config.recurrencia == "mensual"):
            ahora_ec = datetime.now(ECUADOR_TZ)
            dia_target = min(max(payload.dia_mes, 1), 31)
            try:
                config.fecha_programada = ahora_ec.replace(day=dia_target, hour=0, minute=0, second=0, microsecond=0)
            except ValueError:
                config.fecha_programada = ahora_ec.replace(day=28, hour=0, minute=0, second=0, microsecond=0)
        
        if payload.recurrencia is not None:
            config.recurrencia = payload.recurrencia

        if payload.desde_cliente_id is not None:
            if payload.desde_cliente_id and int(payload.desde_cliente_id) > 0:
                config.desde_cliente_id = int(payload.desde_cliente_id)
            else:
                config.desde_cliente_id = None

        if payload.nodo is not None:
            if payload.nodo == "vaciar" or str(payload.nodo).lower() in ["todos", "all", "todos los nodos", ""]:
                config.nodo = None
            else:
                config.nodo = payload.nodo.strip()
            
        db.commit()
        
        return {"success": True, "message": "Configuración actualizada"}
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/configuracion/{config_id}", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def eliminar_configuracion(
    config_id: int,
    db: Session = Depends(get_db)
):
    """Elimina una configuración de envío programado"""
    try:
        config = db.query(models.WhatsAppConfiguracion).filter(
            models.WhatsAppConfiguracion.id == config_id
        ).first()
        
        if not config:
            raise HTTPException(status_code=404, detail="Configuración no encontrada")
        
        db.delete(config)
        db.commit()
        
        return {"success": True, "message": "Configuración eliminada"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ========================================================================
# ADMINISTRADORES DE WHATSAPP
# ========================================================================

@router.get("/administradores", dependencies=[Depends(require_role(["administrador", "secretario"]))])
def listar_administradores_whatsapp(db: Session = Depends(get_db)):
    """Obtiene la lista de números telefónicos autorizados como Administradores en WhatsApp"""
    try:
        admins = db.query(models.WhatsAppAdministrador).order_by(models.WhatsAppAdministrador.fecha_creacion.desc()).all()
        return [
            {
                "id": a.id,
                "numero": a.numero,
                "nombre": a.nombre,
                "permisos": a.permisos or "admin_total",
                "activo": a.activo,
                "fecha_creacion": a.fecha_creacion.strftime("%Y-%m-%d %H:%M:%S") if a.fecha_creacion else None
            }
            for a in admins
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al listar administradores: {str(e)}")


@router.post("/administradores", dependencies=[Depends(require_role(["administrador"]))])
def crear_administrador_whatsapp(
    payload: schemas.WhatsAppAdministradorCreate,
    db: Session = Depends(get_db)
):
    """Registra un nuevo número telefónico autorizado como Administrador"""
    try:
        if not payload.numero or not payload.nombre:
            raise HTTPException(status_code=400, detail="El número y el nombre son obligatorios")
            
        num_limpio = whatsapp_service.format_whatsapp_number(payload.numero)
        if not num_limpio:
            raise HTTPException(status_code=400, detail="Número de teléfono inválido")

        existente = db.query(models.WhatsAppAdministrador).filter(
            models.WhatsAppAdministrador.numero == num_limpio
        ).first()
        
        if existente:
            raise HTTPException(status_code=400, detail=f"El número {num_limpio} ya se encuentra registrado como Administrador.")

        nuevo_admin = models.WhatsAppAdministrador(
            numero=num_limpio,
            nombre=payload.nombre.strip(),
            permisos=payload.permisos or "admin_total",
            activo=payload.activo if payload.activo is not None else True,
            fecha_creacion=datetime.now(ECUADOR_TZ)
        )
        db.add(nuevo_admin)
        db.commit()
        db.refresh(nuevo_admin)

        return {
            "success": True,
            "message": f"Administrador {nuevo_admin.nombre} registrado exitosamente",
            "id": nuevo_admin.id
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al registrar administrador: {str(e)}")


@router.patch("/administradores/{admin_id}", dependencies=[Depends(require_role(["administrador"]))])
def actualizar_administrador_whatsapp(
    admin_id: int,
    payload: schemas.WhatsAppAdministradorUpdate,
    db: Session = Depends(get_db)
):
    """Actualiza la información de un número administrador"""
    try:
        admin = db.query(models.WhatsAppAdministrador).filter(
            models.WhatsAppAdministrador.id == admin_id
        ).first()

        if not admin:
            raise HTTPException(status_code=404, detail="Administrador no encontrado")

        if payload.nombre is not None:
            admin.nombre = payload.nombre.strip()

        if payload.numero is not None:
            num_limpio = whatsapp_service.format_whatsapp_number(payload.numero)
            if num_limpio:
                admin.numero = num_limpio

        if payload.permisos is not None:
            admin.permisos = payload.permisos

        if payload.activo is not None:
            admin.activo = payload.activo

        db.commit()
        return {"success": True, "message": "Administrador actualizado correctamente"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al actualizar administrador: {str(e)}")


@router.delete("/administradores/{admin_id}", dependencies=[Depends(require_role(["administrador"]))])
def eliminar_administrador_whatsapp(
    admin_id: int,
    db: Session = Depends(get_db)
):
    """Elimina un número administrador"""
    try:
        admin = db.query(models.WhatsAppAdministrador).filter(
            models.WhatsAppAdministrador.id == admin_id
        ).first()

        if not admin:
            raise HTTPException(status_code=404, detail="Administrador no encontrado")

        db.delete(admin)
        db.commit()
        return {"success": True, "message": "Administrador eliminado correctamente"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar administrador: {str(e)}")

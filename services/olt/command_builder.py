"""
Constructor y validador de comandos CLI Huawei para OLT.
Genera secuencias para activación, retiro, cambio de vlan/bridge y análisis de errores.
"""
import logging
import unicodedata
from typing import Dict, Any, List

from .exceptions import OLTCommandError, OLTAlreadyExistsError

logger = logging.getLogger(__name__)


def build_activation_commands(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Construye la secuencia de comandos Huawei para activar un ONT.
    
    Returns:
        Diccionario con las claves:
          - 'gpon_commands': lista de comandos para ejecutar en (config-if-gpon-X/X)#
          - 'config_commands': lista de comandos para ejecutar en (config)#
          - 'metadata': todos los valores calculados para persistencia posterior
    """
    gpon_port = payload.get('gpon_port', '0/0/0')
    ont_id = payload.get('ont_id', '0')
    mac = payload.get('mac', '000000000000')
    description = payload.get('description', f'ONT_{ont_id}')

    parts = [p.strip() for p in str(gpon_port).split('/') if p.strip()]
    if len(parts) >= 3:
        interface = f"{parts[0]}/{parts[1]}"
        port_num = parts[2]
    else:
        interface = "0/0"
        port_num = "0"

    try:
        puerto_val = int(port_num)
    except ValueError:
        puerto_val = 0

    # Detectar si es Sayausí (slot 1 o puerto 0/1/x o nodo SAYAUSI)
    is_sayausi = False
    if len(parts) >= 2 and parts[1] == "1":
        is_sayausi = True
    elif payload.get("nodo"):
        s = unicodedata.normalize('NFD', str(payload.get("nodo"))).encode('ascii', 'ignore').decode('utf-8').upper()
        if "SAYAUSI" in s:
            is_sayausi = True

    # Calcular valores por defecto basados en el puerto GPON / Slot
    if is_sayausi:
        derived_profile = str(400 + puerto_val)   # Ej: 408 para puerto 8
        derived_vlan = str(400 + puerto_val)      # Ej: 408 para puerto 8
        derived_user_vlan = str(400 + puerto_val) # Ej: 408 para puerto 8
    else:
        derived_profile = str(100 + puerto_val)   # Ej: 108 para puerto 8
        derived_vlan = str(300 + puerto_val)      # Ej: 308 para puerto 8
        derived_user_vlan = str(100 + puerto_val) # Ej: 108 para puerto 8

    # Validar y limpiar profile_id
    profile_id = payload.get('profile_id')
    if not profile_id or not str(profile_id).isdigit() or (is_sayausi and str(profile_id).startswith('1')):
        profile_id = derived_profile

    # Validar y limpiar srvprofile_id
    srvprofile_id = payload.get('srvprofile_id')
    if not srvprofile_id or not str(srvprofile_id).isdigit() or (is_sayausi and str(srvprofile_id).startswith('1')):
        srvprofile_id = derived_profile

    # Validar y limpiar vlan (VLAN de la OLT para service-port)
    vlan = payload.get('vlan')
    if not vlan or not str(vlan).isdigit() or (is_sayausi and str(vlan).startswith('3')):
        vlan = derived_vlan

    # Validar y limpiar user_vlan (VLAN nativa del cliente / traducción)
    user_vlan = payload.get('user_vlan')
    if not user_vlan or not str(user_vlan).isdigit() or (is_sayausi and str(user_vlan).startswith('1')):
        user_vlan = derived_user_vlan

    # Validar y limpiar service_port
    service_port = payload.get('service_port')
    if not service_port or not str(service_port).isdigit():
        try:
            ont_val = int(ont_id)
        except ValueError:
            ont_val = 0
        service_port = str(ont_val + 1000)

    # Determinar el tipo de aprovisionamiento (por defecto 'bridge' si no se especifica)
    provision_type = payload.get('provision_type', 'bridge')
    if isinstance(provision_type, str):
        provision_type = provision_type.strip().lower()
    if provision_type not in ('ont', 'bridge'):
        provision_type = 'bridge'

    cmd_ont = f'ont add {port_num} {ont_id} sn-auth "{mac}" omci ont-lineprofile-id {profile_id} ont-srvprofile-id {srvprofile_id} desc "{description}"'
    cmd_breach = f'ont port native-vlan {port_num} {ont_id} eth 1 vlan {user_vlan} priority 0'
    cmd_servicio = f'service-port {service_port} vlan {vlan} gpon {gpon_port} ont {ont_id} gemport {profile_id} multi-service user-vlan {user_vlan} tag-transform translate'

    if provision_type == 'ont':
        gpon_commands = [cmd_ont]
    else:
        gpon_commands = [cmd_ont, cmd_breach]

    return {
        'gpon_commands': gpon_commands,
        'config_commands': [
            cmd_servicio,
        ],
        'metadata': {
            'gpon_port': gpon_port,
            'port_num': port_num,
            'puerto_val': puerto_val,
            'ont_id': ont_id,
            'mac': mac,
            'service_port': service_port,
            'vlan': vlan,
            'user_vlan': user_vlan,
            'profile_id': profile_id,
            'srvprofile_id': srvprofile_id,
            'description': description,
            'cmd_ont': cmd_ont,
            'cmd_breach': cmd_breach if provision_type == 'bridge' else None,
            'cmd_servicio': cmd_servicio,
            'provision_type': provision_type,
        }
    }


def check_response_for_errors(command: str, response: str) -> None:
    """
    Analiza la respuesta de la OLT ante un comando específico.
    Si detecta un error, levanta OLTCommandError con la descripción del error.
    Trata los errores de entidad ya existente/duplicada como advertencias no fatales.
    """
    resp_lower = response.lower()
    
    non_fatal_keywords = [
        'already existed',
        'already exists',
        'has existed',
        'exist',
        'make configuration repeatedly',
        'configuration repeatedly',
        'repeatedly',
        'the same configuration',
        'same configuration',
        'the same as',
        'is the same',
        'has already been configured',
        'already configured'
    ]
    
    error_keywords = [
        'failure:',
        'error:',
        'unknown command',
        'parameter error',
        'invalid',
        'no such command',
        'command not found',
        'does not exist',
        'is invalid',
        'command name is incorrect'
    ]
    
    for kw in error_keywords:
        if kw in resp_lower:
            if any(nf in resp_lower for nf in non_fatal_keywords):
                logger.warning(f"Entidad ya existente detectada en respuesta a '{command}': {response.strip()}")
                raise OLTAlreadyExistsError(f"Entidad ya existente: {response.strip()}")
            
            lines = response.split('\n')
            error_line = next((line.strip() for line in lines if kw in line.lower()), response.strip())
            logger.error(f"Error detectado en respuesta al comando '{command}': {error_line}")
            raise OLTCommandError(f"Error OLT en '{command}': {error_line}")


def build_removal_commands(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Construye la secuencia de comandos Huawei para eliminar un ONT."""
    gpon_port = payload.get('gpon_port', '0/0/0')
    ont_id = payload.get('ont_id', '0')
    service_port = str(payload.get('service_port', '')).strip()
    
    parts = [p.strip() for p in str(gpon_port).split('/') if p.strip()]
    if len(parts) >= 3:
        port_num = parts[2]
    else:
        port_num = "0"

    config_commands_before = []
    if service_port and service_port.isdigit():
        config_commands_before.append(f"undo service-port {service_port}")
    else:
        logger.warning(f"service_port inválido o vacío ('{service_port}'), se omite undo service-port")

    return {
        'config_commands_before': config_commands_before,
        'gpon_commands': [
            f"ont delete {port_num} {ont_id}",
        ],
    }


def build_set_breach_commands(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Construye la secuencia de comandos Huawei para cambiar la VLAN nativa (Bridge)."""
    gpon_port = payload.get('gpon_port', '0/0/0')
    ont_id = payload.get('ont_id', '0')
    priority = payload.get('priority', '0')

    parts = [p.strip() for p in str(gpon_port).split('/') if p.strip()]
    if len(parts) >= 3:
        interface = f"{parts[0]}/{parts[1]}"
        port_num = parts[2]
    else:
        interface = "0/0"
        port_num = "0"

    try:
        puerto_val = int(port_num)
    except ValueError:
        puerto_val = 0

    is_sayausi_breach = len(parts) >= 2 and parts[1] == "1"
    vlan = payload.get('vlan', payload.get('user_vlan'))
    if not vlan or not str(vlan).isdigit() or (is_sayausi_breach and str(vlan).startswith('1')):
        vlan = str(400 + puerto_val) if is_sayausi_breach else str(100 + puerto_val)

    return {
        'gpon_commands': [
            f"ont port native-vlan {port_num} {ont_id} eth 1 vlan {vlan} priority {priority}",
        ],
    }

"""
OPSATEL ISP - Command Sanitizer
==============================
Módulo de SEGURIDAD crítico para prevenir inyección de comandos en OLT.
Todas las variables que van a la OLT DEBEN pasar por este sanitizer.

Autor: Arquitecto de Software Senior
Versión: 1.0.0
"""

import re
import logging
from typing import Dict, Any, Tuple, Optional
from datetime import datetime
from ipaddress import IPv4Address, IPv4Network, AddressValueError

# Configurar logging
logger = logging.getLogger(__name__)

class CommandSanitizationError(Exception):
    """Excepción cuando un comando falla validación"""
    pass

class CommandSanitizer:
    """
    Sanitizador de comandos para OLT Huawei.
    Todas las funciones son STATIC para uso directo sin instanciar.
    """
    
    # ========== CONSTANTES DE VALIDACIÓN ==========
    MAX_DESCRIPTION_LENGTH = 31  # Límite de caracteres en descripción ONT
    MIN_POWER_DBM = -27.0
    MAX_POWER_DBM = -5.0
    
    # Expresiones regulares compiladas
    REGEX_MAC = re.compile(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$')
    REGEX_MAC_NO_SEPARATOR = re.compile(r'^[0-9A-Fa-f]{12}$')
    REGEX_GPON_SN_HEX = re.compile(r'^[0-9A-Fa-f]{16}$')
    REGEX_GPON_SN_ASCII = re.compile(r'^[A-Za-z]{4}[0-9A-Fa-f]{8}$')
    REGEX_GPON_PORT = re.compile(r'^0/\d{1,2}/\d{1,2}$')  # 0/SLOT/PORT (ej: 0/2/1)
    REGEX_ONT_ID = re.compile(r'^\d{1,3}$')  # 0-127 (en la práctica)
    REGEX_VLAN_ID = re.compile(r'^[0-9]{1,4}$')  # 0-4095 para VLAN
    REGEX_DESCRIPTION = re.compile(r'^[a-zA-Z0-9\-_\s]{1,31}$')  # Solo alfanuméricos, guion, guion bajo, espacio
    REGEX_IP = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')
    
    # Whitelist de caracteres permitidos (para escape)
    ALLOWED_CHARS = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_. ')
    
    @staticmethod
    def validate_mac(mac: str) -> str:
        """
        Valida y normaliza direcciones MAC o GPON SN.
        Acepta: AA:BB:CC:DD:EE:FF, AA-BB-CC-DD-EE-FF, AABBCCDDEEFF, GPON SN (16 hex o 4 letras + 8 hex)
        Retorna: MAC/SN normalizado (sin separadores, uppercase)
        
        Args:
            mac: Dirección MAC o SN a validar
            
        Returns:
            MAC/SN normalizado (sin separadores, uppercase)
            
        Raises:
            CommandSanitizationError: Si MAC/SN es inválida
        """
        if not isinstance(mac, str):
            raise CommandSanitizationError(f"MAC/SN debe ser string, recibido {type(mac)}")
        
        mac_clean = mac.strip().upper()
        
        # Intentar parsear con separadores
        if CommandSanitizer.REGEX_MAC.match(mac_clean):
            mac_clean = mac_clean.replace(':', '').replace('-', '')
            return mac_clean
        # O directo sin separadores
        elif (CommandSanitizer.REGEX_MAC_NO_SEPARATOR.match(mac_clean) or
              CommandSanitizer.REGEX_GPON_SN_HEX.match(mac_clean) or
              CommandSanitizer.REGEX_GPON_SN_ASCII.match(mac_clean)):
            return mac_clean
        else:
            raise CommandSanitizationError(
                f"MAC/SN '{mac}' inválido. Debe ser una MAC (AABBCCDDEEFF) o GPON SN (16 hex o 4 letras + 8 hex)"
            )
        
        logger.debug(f"MAC validado: {mac} → {mac_clean}")
        return mac_clean
    
    @staticmethod
    def validate_gpon_port(port: str) -> str:
        """
        Valida puerto GPON (ej: 0/0/1 o 0/1/1).
        
        Args:
            port: Puerto GPON a validar
            
        Returns:
            Puerto validado
            
        Raises:
            CommandSanitizationError: Si puerto es inválido
        """
        if not isinstance(port, str):
            raise CommandSanitizationError(f"Puerto GPON debe ser string")
        
        port_clean = port.strip()
        
        if not CommandSanitizer.REGEX_GPON_PORT.match(port_clean):
            raise CommandSanitizationError(
                f"Puerto GPON '{port}' inválido. Formato: 0/0/X o 0/1/X (donde X es 0-127)"
            )
        
        return port_clean
    
    @staticmethod
    def validate_ont_id(ont_id: str) -> str:
        """
        Valida ID de ONT (0-127).
        """
        if not isinstance(ont_id, (str, int)):
            raise CommandSanitizationError("ONT ID debe ser string o int")
        
        try:
            ont_num = int(str(ont_id).strip())
        except ValueError:
            raise CommandSanitizationError(f"ONT ID '{ont_id}' no es un número válido")
        
        if not (0 <= ont_num <= 127):
            raise CommandSanitizationError(f"ONT ID {ont_num} fuera de rango (0-127)")
        
        return str(ont_num)
    
    @staticmethod
    def validate_vlan_id(vlan: str) -> str:
        """
        Valida VLAN ID (0-4095).
        """
        if not isinstance(vlan, (str, int)):
            raise CommandSanitizationError("VLAN debe ser string o int")
        
        try:
            vlan_num = int(str(vlan).strip())
        except ValueError:
            raise CommandSanitizationError(f"VLAN '{vlan}' no es un número válido")
        
        if not (0 <= vlan_num <= 4095):
            raise CommandSanitizationError(f"VLAN {vlan_num} fuera de rango (0-4095)")
        
        return str(vlan_num)
    
    @staticmethod
    def validate_description(desc: str) -> str:
        """
        Valida descripción de ONT (max 31 caracteres, alfanuméricos + guion + underscore).
        
        Args:
            desc: Descripción a validar
            
        Returns:
            Descripción validada
            
        Raises:
            CommandSanitizationError: Si descripción es inválida
        """
        if not isinstance(desc, str):
            raise CommandSanitizationError("Descripción debe ser string")
        
        desc_clean = desc.strip()
        
        # Limitar longitud
        if len(desc_clean) > CommandSanitizer.MAX_DESCRIPTION_LENGTH:
            desc_clean = desc_clean[:CommandSanitizer.MAX_DESCRIPTION_LENGTH]
            logger.warning(f"Descripción truncada a {CommandSanitizer.MAX_DESCRIPTION_LENGTH} caracteres")
        
        # Validar caracteres permitidos
        if not CommandSanitizer.REGEX_DESCRIPTION.match(desc_clean):
            # Intentar sanitizar removiendo caracteres especiales
            desc_clean = re.sub(r'[^a-zA-Z0-9\-_\s]', '', desc_clean).strip()
            if not desc_clean:
                raise CommandSanitizationError("Descripción vacía después de sanitización")
            logger.warning(f"Descripción sanitizada a: {desc_clean}")
        
        return desc_clean
    
    @staticmethod
    def validate_ip_address(ip: str) -> str:
        """
        Valida dirección IP (IPv4).
        
        Args:
            ip: IP a validar
            
        Returns:
            IP validada
            
        Raises:
            CommandSanitizationError: Si IP es inválida
        """
        if not isinstance(ip, str):
            raise CommandSanitizationError("IP debe ser string")
        
        ip_clean = ip.strip()
        
        try:
            # Validar que sea IPv4 válido
            IPv4Address(ip_clean)
        except AddressValueError:
            raise CommandSanitizationError(f"IP '{ip}' no es una dirección IPv4 válida")
        
        return ip_clean
    
    @staticmethod
    def validate_power(power: str) -> float:
        """
        Valida valor de potencia (dBm).
        
        Args:
            power: Potencia a validar (ej: "-23.45")
            
        Returns:
            Potencia como float
            
        Raises:
            CommandSanitizationError: Si potencia es inválida
        """
        if not isinstance(power, (str, int, float)):
            raise CommandSanitizationError("Potencia debe ser string, int o float")
        
        try:
            power_val = float(str(power).strip().replace(',', '.'))
        except ValueError:
            raise CommandSanitizationError(f"Potencia '{power}' no es un número válido")
        
        if power_val < CommandSanitizer.MIN_POWER_DBM or power_val > CommandSanitizer.MAX_POWER_DBM:
            raise CommandSanitizationError(
                f"Potencia {power_val} dBm fuera de rango ({CommandSanitizer.MIN_POWER_DBM} a {CommandSanitizer.MAX_POWER_DBM})"
            )
        
        return power_val
    
    @staticmethod
    def sanitize_text(text: str, max_length: int = 255) -> str:
        """
        Sanitiza texto genérico (remove caracteres peligrosos, limita longitud).
        
        Args:
            text: Texto a sanitizar
            max_length: Máxima longitud permitida
            
        Returns:
            Texto sanitizado
        """
        if not isinstance(text, str):
            return str(text)[:max_length]
        
        text_clean = text.strip()
        
        # Remover caracteres peligrosos (anything except alphanumeric, spaces, guion, underscore, punto)
        text_clean = re.sub(r'[^a-zA-Z0-9\-_\s\.]', '', text_clean)
        
        # Limitar longitud
        if len(text_clean) > max_length:
            text_clean = text_clean[:max_length]
        
        return text_clean
    
    @staticmethod
    def validate_payload(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Valida y sanitiza un payload completo para una acción.
        Este es el punto de entrada crítico de seguridad.
        
        Args:
            action: Tipo de acción ('add_ont', 'add_service', etc.)
            payload: Payload JSON a validar
            
        Returns:
            Payload validado y sanitizado
            
        Raises:
            CommandSanitizationError: Si payload es inválido
        """
        if not isinstance(payload, dict):
            raise CommandSanitizationError("Payload debe ser un diccionario")
        
        validated = {}
        
        # Validaciones comunes (todos necesitan MAC)
        if action in ['add_ont', 'add_service', 'set_breach', 'check_power']:
            if 'mac' not in payload:
                raise CommandSanitizationError(f"Payload para '{action}' requiere 'mac'")
            validated['mac'] = CommandSanitizer.validate_mac(payload['mac'])
        
        # Validaciones por acción
        if action == 'add_ont':
            validated['gpon_port'] = CommandSanitizer.validate_gpon_port(payload.get('gpon_port', '0/0/0'))
            validated['ont_id'] = CommandSanitizer.validate_ont_id(payload.get('ont_id', '0'))
            validated['description'] = CommandSanitizer.validate_description(payload.get('description', 'DEFAULT'))
            # OPCIONALes
            if 'profile_id' in payload:
                validated['profile_id'] = CommandSanitizer.validate_vlan_id(payload['profile_id'])
            if 'srvprofile_id' in payload:
                validated['srvprofile_id'] = CommandSanitizer.validate_vlan_id(payload['srvprofile_id'])
        
        elif action == 'add_service':
            validated['service_port'] = CommandSanitizer.sanitize_text(payload.get('service_port', '0'), 10)
            validated['vlan'] = CommandSanitizer.validate_vlan_id(payload.get('vlan', '100'))
            validated['gpon_port'] = CommandSanitizer.validate_gpon_port(payload.get('gpon_port', '0/0/0'))
            validated['ont_id'] = CommandSanitizer.validate_ont_id(payload.get('ont_id', '0'))
            validated['gemport'] = CommandSanitizer.sanitize_text(payload.get('gemport', '0'), 10)
            if 'user_vlan' in payload:
                validated['user_vlan'] = CommandSanitizer.validate_vlan_id(payload['user_vlan'])
        
        elif action == 'check_power':
            validated['gpon_port'] = CommandSanitizer.validate_gpon_port(payload.get('gpon_port', '0/0/0'))
            validated['ont_id'] = CommandSanitizer.validate_ont_id(payload.get('ont_id', '0'))
        
        elif action == 'set_breach':
            validated['gpon_port'] = CommandSanitizer.validate_gpon_port(payload.get('gpon_port', '0/0/0'))
            validated['ont_id'] = CommandSanitizer.validate_ont_id(payload.get('ont_id', '0'))
            validated['vlan'] = CommandSanitizer.validate_vlan_id(payload.get('vlan', '100'))
            validated['priority'] = CommandSanitizer.sanitize_text(payload.get('priority', '0'), 1)
        
        elif action == 'remove_ont':
            validated['gpon_port'] = CommandSanitizer.validate_gpon_port(payload.get('gpon_port', '0/0/0'))
            validated['ont_id'] = CommandSanitizer.validate_ont_id(payload.get('ont_id', '0'))
            validated['service_port'] = CommandSanitizer.sanitize_text(payload.get('service_port', '0'), 10)
        
        
        # Copiar campos adicionales sanitizados
        for key, value in payload.items():
            if key not in validated:  # No duplicar
                validated[key] = CommandSanitizer.sanitize_text(str(value), 255)
        
        logger.info(f"Payload validado para '{action}': {list(validated.keys())}")
        return validated


# ============================================================================
# FUNCIONES DE TESTING (borrar en producción)
# ============================================================================

def test_sanitizer():
    """Tests unitarios básicos"""
    print("=" * 60)
    print("TESTING: CommandSanitizer")
    print("=" * 60)
    
    # Test MAC & GPON SN
    try:
        assert CommandSanitizer.validate_mac("AA:BB:CC:DD:EE:FF") == "AABBCCDDEEFF"
        assert CommandSanitizer.validate_mac("AA-BB-CC-DD-EE-FF") == "AABBCCDDEEFF"
        assert CommandSanitizer.validate_mac("AABBCCDDEEFF") == "AABBCCDDEEFF"
        assert CommandSanitizer.validate_mac("48575443B0C1D2E3") == "48575443B0C1D2E3"
        assert CommandSanitizer.validate_mac("HWTCB0C1D2E3") == "HWTCB0C1D2E3"
        print("✓ MAC/SN validation OK")
    except Exception as e:
        print(f"✗ MAC/SN validation FAILED: {e}")
    
    # Test GPON
    try:
        assert CommandSanitizer.validate_gpon_port("0/0/1") == "0/0/1"
        assert CommandSanitizer.validate_gpon_port("0/1/15") == "0/1/15"
        print("✓ GPON port validation OK")
    except Exception as e:
        print(f"✗ GPON validation FAILED: {e}")
    
    # Test Description
    try:
        assert CommandSanitizer.validate_description("Cliente001") == "Cliente001"
        desc_long = "a" * 50
        result = CommandSanitizer.validate_description(desc_long)
        assert len(result) == 31
        print("✓ Description validation OK")
    except Exception as e:
        print(f"✗ Description validation FAILED: {e}")
    
    # Test VLAN
    try:
        assert CommandSanitizer.validate_vlan_id("100") == "100"
        assert CommandSanitizer.validate_vlan_id("4095") == "4095"
        print("✓ VLAN validation OK")
    except Exception as e:
        print(f"✗ VLAN validation FAILED: {e}")
    
    # Test IP
    try:
        assert CommandSanitizer.validate_ip_address("172.16.1.100") == "172.16.1.100"
        print("✓ IP validation OK")
    except Exception as e:
        print(f"✗ IP validation FAILED: {e}")
    
    # Test Power
    try:
        assert CommandSanitizer.validate_power("-23.45") == -23.45
        assert CommandSanitizer.validate_power("-27") == -27.0
        print("✓ Power validation OK")
    except Exception as e:
        print(f"✗ Power validation FAILED: {e}")
    
    # Test Payload
    try:
        payload = {
            'mac': 'AA:BB:CC:DD:EE:FF',
            'gpon_port': '0/0/1',
            'ont_id': '1',
            'description': 'Cliente Test',
            'profile_id': '101'
        }
        validated = CommandSanitizer.validate_payload('add_ont', payload)
        assert validated['mac'] == 'AABBCCDDEEFF'
        assert validated['ont_id'] == '1'
        print("✓ Payload validation OK")
    except Exception as e:
        print(f"✗ Payload validation FAILED: {e}")
    
    print("=" * 60)
    print("TESTING COMPLETE\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_sanitizer()

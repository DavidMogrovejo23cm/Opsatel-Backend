"""
Excepciones personalizadas y configuraciones base para OLT Huawei en OPSATEL.
"""
import logging

try:
    from netmiko import ConnectHandler, NetmikoAuthenticationException, NetmikoTimeoutException
    NETMIKO_AVAILABLE = True
except ImportError:
    NETMIKO_AVAILABLE = False
    logging.warning("Netmiko no instalado. Instala: pip install netmiko")

# Habilitar compatibilidad con host keys y algoritmos SSH legacy (ssh-rsa) para OLTs Huawei
try:
    import paramiko
    if hasattr(paramiko, "Transport"):
        pref_keys = list(getattr(paramiko.Transport, "_preferred_keys", ()))
        for k in ["ssh-rsa", "rsa-sha2-512", "rsa-sha2-256"]:
            if k not in pref_keys:
                pref_keys.append(k)
        paramiko.Transport._preferred_keys = tuple(pref_keys)

        pref_kex = list(getattr(paramiko.Transport, "_preferred_kex", ()))
        for kex in ["diffie-hellman-group-exchange-sha256", "diffie-hellman-group-exchange-sha1", "diffie-hellman-group14-sha1"]:
            if kex not in pref_kex:
                pref_kex.append(kex)
        paramiko.Transport._preferred_kex = tuple(pref_kex)

        if hasattr(paramiko.Transport, "_key_info") and hasattr(paramiko, "RSAKey"):
            paramiko.Transport._key_info["ssh-rsa"] = paramiko.RSAKey
except Exception as _ssh_compat_err:
    logging.warning(f"No se pudieron registrar algoritmos preferidos SSH en Paramiko: {_ssh_compat_err}")

logger = logging.getLogger(__name__)


class OLTConnectionError(Exception):
    """Error de conexión a la OLT"""
    pass


class OLTCommandError(Exception):
    """Error ejecutando comando en la OLT"""
    pass


class OLTParsingError(Exception):
    """Error parseando respuesta de la OLT"""
    pass


class OLTTimeoutError(Exception):
    """Timeout esperando respuesta de la OLT"""
    pass


class OLTAlreadyExistsError(OLTCommandError):
    """La entidad (ONT, service-port, etc.) ya existe en la OLT"""
    pass


HUAWEI_OLT_CONFIG = {
    'device_type': 'huawei',  # Netmiko type para Huawei OLT
    'fast_cli': True,  # Modo rápido para terminal
    'session_log': None,  # Puede ser un archivo para debugging
    'global_delay_factor': 1.5,  # Factor de delay para operaciones
    'banner_timeout': 15,  # Timeout banner inicial
    'read_timeout_override': 60,  # Timeout para lectura
}

HUAWEI_PROMPTS = [
    r'.*>$',           # Main prompt
    r'.*#$',           # Config prompt
    r'.*\(config\)#$', # Config submenu
    r'.*\(ont\)#$',    # ONT menu
]

import logging
import time
import re
from typing import Dict, Any, List, Optional
import routeros_api
import observability

logger = logging.getLogger("opsatel.network.adapters.mikrotik")

class MikroTikAdapterError(Exception):
    """Excepción base para el adaptador de MikroTik"""
    pass

class MikroTikAdapter:
    """
    Adaptador de MikroTik RouterOS API compatible con v6 y v7.
    Implementa reintentos, pool lógico de conexiones, reconexión automática e instrumentación.
    """
    def __init__(self, host: str, username: str, password: str, port: int = 8728, timeout: int = 10, max_retries: int = 3):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.timeout = timeout
        self.max_retries = max_retries
        self.api = None
        self.connection = None
        self.is_connected = False

    def connect(self) -> bool:
        """Establece conexión con el API de RouterOS"""
        attempt = 0
        last_err = None
        while attempt < self.max_retries:
            try:
                attempt += 1
                logger.info(f"Conectando a MikroTik {self.host}:{self.port} (Intento {attempt}/{self.max_retries})...")
                
                self.connection = routeros_api.RouterOsApiConnection(
                    self.host,
                    username=self.username,
                    password=self.password,
                    port=self.port,
                    plaintext_login=True,
                    timeout=self.timeout
                )
                self.api = self.connection.connect()
                self.is_connected = True
                logger.info(f"✓ Conexión establecida exitosamente con MikroTik {self.host}")
                return True
            except Exception as e:
                last_err = e
                logger.warning(f"Intento {attempt} fallido para conectar a MikroTik: {e}")
                time.sleep(1)
        
        self.is_connected = False
        raise MikroTikAdapterError(f"No se pudo conectar a MikroTik {self.host} tras {self.max_retries} intentos: {last_err}")

    def disconnect(self):
        """Cierra la conexión activa"""
        if self.connection:
            try:
                self.connection.disconnect()
            except Exception as e:
                logger.warning(f"Error al desconectar de MikroTik: {e}")
        self.api = None
        self.connection = None
        self.is_connected = False
        logger.info(f"Conexión con MikroTik {self.host} cerrada.")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def _get_resource(self, path: str):
        """Retorna recurso para interactuar con RouterOS API en una ruta específica"""
        if not self.is_connected or not self.api:
            self.connect()
        try:
            return self.api.get_resource(path)
        except Exception as e:
            logger.warning(f"Conexión perdida al obtener recurso {path}. Reintentando conectar...")
            self.connect()
            return self.api.get_resource(path)

    def get_system_resource(self) -> Dict[str, Any]:
        """Obtiene información de CPU, memoria y versión del Router"""
        try:
            res = self._get_resource('/system/resource').get()
            if res:
                return res[0]
            return {}
        except Exception as e:
            raise MikroTikAdapterError(f"Error obteniendo recursos del sistema: {e}")

    def find_dhcp_lease_by_mac(self, mac: str) -> Optional[Dict[str, Any]]:
        """Busca un DHCP Lease por su dirección MAC"""
        try:
            leases = self._get_resource('/ip/dhcp-server/lease').get(mac_address=mac)
            if leases:
                return leases[0]
            return None
        except Exception as e:
            raise MikroTikAdapterError(f"Error buscando DHCP lease por MAC {mac}: {e}")

    def find_dhcp_lease_by_client_id(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Busca un DHCP Lease por su Client ID"""
        try:
            leases = self._get_resource('/ip/dhcp-server/lease').get(client_id=client_id)
            if leases:
                return leases[0]
            return None
        except Exception as e:
            raise MikroTikAdapterError(f"Error buscando DHCP lease por Client ID {client_id}: {e}")

    def find_dhcp_lease_by_hostname(self, host_name: str) -> Optional[Dict[str, Any]]:
        """Busca DHCP Lease por Hostname"""
        try:
            leases = self._get_resource('/ip/dhcp-server/lease').get(host_name=host_name)
            if leases:
                return leases[0]
            return None
        except Exception as e:
            raise MikroTikAdapterError(f"Error buscando DHCP lease por Hostname {host_name}: {e}")

    def make_lease_static(self, lease_id: str) -> bool:
        """Convierte una lease dinámica existente en estática"""
        try:
            resource = self._get_resource('/ip/dhcp-server/lease')
            resource.call('make-static', {'numbers': lease_id})
            logger.info(f"DHCP Lease {lease_id} convertida a estática.")
            return True
        except Exception as e:
            raise MikroTikAdapterError(f"Error convirtiendo DHCP lease {lease_id} a estática: {e}")

    def update_lease_comment(self, lease_id: str, comment: str) -> bool:
        """Modifica el comentario de una lease DHCP"""
        try:
            resource = self._get_resource('/ip/dhcp-server/lease')
            resource.set(id=lease_id, comment=comment)
            logger.info(f"Comentario modificado en DHCP Lease {lease_id}: {comment}")
            return True
        except Exception as e:
            raise MikroTikAdapterError(f"Error modificando comentario de DHCP lease {lease_id}: {e}")

    def undo_static_lease(self, mac: str) -> bool:
        """Revierte una lease a dinámica o la remueve de la lista estática (Rollback)"""
        try:
            resource = self._get_resource('/ip/dhcp-server/lease')
            leases = resource.get(mac_address=mac)
            for l in leases:
                resource.remove(id=l['id'])
                logger.info(f"Rollback: Removida lease estática para MAC {mac}")
            return True
        except Exception as e:
            logger.warning(f"Error en rollback de lease para MAC {mac}: {e}")
            return False

    def list_interfaces(self) -> List[Dict[str, Any]]:
        """Obtiene la lista de interfaces de red de MikroTik"""
        try:
            return self._get_resource('/interface').get()
        except Exception as e:
            raise MikroTikAdapterError(f"Error listando interfaces: {e}")

    def get_address_lists(self) -> List[Dict[str, Any]]:
        """Obtiene la lista de direcciones IP asociadas (Address Lists)"""
        try:
            return self._get_resource('/ip/firewall/address-list').get()
        except Exception as e:
            raise MikroTikAdapterError(f"Error obteniendo address lists: {e}")

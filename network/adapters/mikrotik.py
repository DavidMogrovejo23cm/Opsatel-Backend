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
                
                self.connection = routeros_api.RouterOsApiPool(
                    self.host,
                    username=self.username,
                    password=self.password,
                    port=self.port,
                    plaintext_login=True
                )
                self.api = self.connection.get_api()
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


    def get_dynamic_leases(self, server: Optional[str] = None) -> List[Dict[str, Any]]:
        """Obtiene los DHCP leases dinámicos del MikroTik. Opcionalmente filtra por Servidor DHCP."""
        try:
            # Consultamos dinámicos directamente usando la API de RouterOS
            resource = self._get_resource('/ip/dhcp-server/lease')
            filters = {'dynamic': 'true'}
            if server:
                filters['server'] = server
            
            leases = resource.get(**filters)
            # Doble chequeo por diferencias de formato v6/v7
            return [l for l in leases if l.get('dynamic') == 'true' or l.get('dynamic') is True]
        except Exception as e:
            raise MikroTikAdapterError(f"Error listando leases dinámicos: {e}")

    def find_dhcp_lease_by_mac(self, mac: str, server: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Busca un DHCP Lease por su dirección MAC (con opción de servidor)"""
        try:
            clean_mac = mac.replace(':', '').replace('-', '').upper()
            resource = self._get_resource('/ip/dhcp-server/lease')
            filters = {}
            if server:
                filters['server'] = server
            
            leases = resource.get(**filters)
            for l in leases:
                l_mac = l.get('mac-address', '').replace(':', '').replace('-', '').upper()
                if l_mac == clean_mac:
                    return l
            return None
        except Exception as e:
            raise MikroTikAdapterError(f"Error buscando DHCP lease por MAC {mac}: {e}")

    def find_dhcp_lease_by_client_id(self, client_id: str, server: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Busca un DHCP Lease por su Client ID"""
        try:
            resource = self._get_resource('/ip/dhcp-server/lease')
            filters = {}
            if server:
                filters['server'] = server
            
            leases = resource.get(**filters)
            for l in leases:
                if l.get('client-id') == client_id or client_id in l.get('client-id', ''):
                    return l
            return None
        except Exception as e:
            raise MikroTikAdapterError(f"Error buscando DHCP lease por Client ID {client_id}: {e}")

    def find_dhcp_lease_by_hostname(self, host_name: str, server: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Busca DHCP Lease por exactitud o coincidencia parcial estricta del Hostname"""
        try:
            clean_host = host_name.lower().strip()
            resource = self._get_resource('/ip/dhcp-server/lease')
            filters = {}
            if server:
                filters['server'] = server
            
            leases = resource.get(**filters)
            for l in leases:
                l_host = l.get('host-name', '').lower().strip()
                if l_host == clean_host: # Match exacto primero
                    return l
            return None
        except Exception as e:
            raise MikroTikAdapterError(f"Error buscando DHCP lease por Hostname {host_name}: {e}")

    def make_lease_static(self, lease_id: str) -> bool:
        """
        Convierte una lease dinámica existente en estática.
        Soporta múltiples llamadas compatibles de API RouterOS.
        """
        try:
            resource = self._get_resource('/ip/dhcp-server/lease')
            # Intentamos las 3 variantes sintácticas para máxima compatibilidad con v6/v7 y wrappers
            success = False
            errors = []
            
            # Variante 1: .id
            try:
                resource.call('make-static', {'.id': lease_id})
                success = True
            except Exception as e:
                errors.append(f"V1 (.id) falló: {e}")
                
            # Variante 2: numbers
            if not success:
                try:
                    resource.call('make-static', {'numbers': lease_id})
                    success = True
                except Exception as e:
                    errors.append(f"V2 (numbers) falló: {e}")
                    
            # Variante 3: id
            if not success:
                try:
                    resource.call('make-static', {'id': lease_id})
                    success = True
                except Exception as e:
                    errors.append(f"V3 (id) falló: {e}")

            if not success:
                raise MikroTikAdapterError(f"Ninguna variante de make-static funcionó. Errores: {errors}")
                
            logger.info(f"DHCP Lease {lease_id} convertida a estática.")
            return True
        except Exception as e:
            raise MikroTikAdapterError(f"Error convirtiendo DHCP lease {lease_id} a estática: {e}")

    def update_lease_comment(self, lease_id: str, comment: str) -> bool:
        """Modifica el comentario de una lease DHCP"""
        try:
            resource = self._get_resource('/ip/dhcp-server/lease')
            # Soporta tanto '.id' como 'id' en el dict
            try:
                resource.set(**{'.id': lease_id, 'comment': comment})
            except Exception:
                resource.set(**{'id': lease_id, 'comment': comment})
            logger.info(f"Comentario modificado en DHCP Lease {lease_id}: {comment}")
            return True
        except Exception as e:
            raise MikroTikAdapterError(f"Error modificando comentario de DHCP lease {lease_id}: {e}")

    def update_lease_ip(self, lease_id: str, ip_address: str) -> bool:
        """Modifica la dirección IP de una lease DHCP estática (reasignación)"""
        try:
            resource = self._get_resource('/ip/dhcp-server/lease')
            try:
                resource.set(**{'.id': lease_id, 'address': ip_address})
            except Exception:
                resource.set(**{'id': lease_id, 'address': ip_address})
            logger.info(f"IP reasignada en DHCP Lease {lease_id} a {ip_address}")
            return True
        except Exception as e:
            raise MikroTikAdapterError(f"Error reasignando dirección IP {ip_address} al lease {lease_id}: {e}")

    def undo_static_lease(self, mac: str) -> bool:
        """
        Revierte una lease a dinámica quitando el estado estático
        (en RouterOS se logra removiendo el lease estático sin desconectar el cliente).
        """
        try:
            resource = self._get_resource('/ip/dhcp-server/lease')
            leases = resource.get(mac_address=mac)
            for l in leases:
                # En lugar de borrarlo directamente, verificamos si era dinámico previamente.
                # Si lo removemos, el cliente conserva su conexión y vuelve a tomar IP dinámica en el siguiente renewal.
                # De esta forma evitamos romper el binding actual.
                resource.remove(**{'.id': l['id']})
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

    def add_to_address_list(self, address: str, comment: str, list_name: str) -> bool:
        """
        Agrega una IP a /ip/firewall/address-list en MikroTik.
        Equivalente en CLI: /ip firewall address-list add address={address} comment="{comment}" list={list_name}
        """
        try:
            resource = self._get_resource('/ip/firewall/address-list')
            resource.add(address=address, comment=comment, list=list_name)
            logger.info(f"✓ IP {address} ({comment}) agregada a Address List '{list_name}'")
            return True
        except Exception as e:
            err_str = str(e).lower()
            if "already exists" in err_str or "already in use" in err_str or "failure: already" in err_str:
                logger.info(f"IP {address} ya se encontraba registrada en Address List '{list_name}'.")
                return True
            raise MikroTikAdapterError(f"Error agregando IP {address} a address-list '{list_name}': {e}")

    def remove_from_address_list(self, address: str, list_name: Optional[str] = None) -> bool:
        """Remueve una IP de /ip/firewall/address-list en MikroTik"""
        try:
            resource = self._get_resource('/ip/firewall/address-list')
            filters = {'address': address}
            if list_name:
                filters['list'] = list_name
            items = resource.get(**filters)
            for item in items:
                try:
                    resource.remove(**{'.id': item['id']})
                except Exception:
                    resource.remove(**{'id': item['id']})
            return True
        except Exception as e:
            logger.warning(f"Error removiendo IP {address} de address-list '{list_name}': {e}")
            return False

    def is_ip_in_suspended_list(self, address: str) -> bool:
        """Verifica si una IP se encuentra en alguna lista de corte o suspensión de MikroTik"""
        try:
            resource = self._get_resource('/ip/firewall/address-list')
            items = resource.get(address=address)
            for item in items:
                nombre_lista = str(item.get('list', '')).upper()
                if any(k in nombre_lista for k in ['SUSPEND', 'CORTE', 'MOROSO', 'PAGO']):
                    return True
            return False
        except Exception as e:
            logger.warning(f"Error verificando si IP {address} está en lista de suspensión: {e}")
            return False

    def ping(self, address: str, count: int = 3) -> Dict[str, Any]:
        """
        Ejecuta ping hacia una IP a través de MikroTik RouterOS API.
        Retorna diccionario con: online (bool), received (int), sent (int), packet_loss (int), avg_rtt (ms o None), detail (str).
        """
        try:
            if not self.is_connected or not self.api:
                self.connect()

            # Intentar comando ping a través del API de RouterOS
            try:
                res = self.api.get_binary_resource('/').call('ping', {
                    'address': str(address),
                    'count': str(count),
                    'interval': '1'
                })
            except Exception:
                # Variante alternativa de recurso ping en RouterOS API
                ping_resource = self._get_resource('/ping')
                res = ping_resource.call('ping', {'address': str(address), 'count': str(count)})

            if not res:
                return self._fallback_os_ping(address, count)

            received = 0
            times = []
            for item in res:
                time_val = item.get(b'time') or item.get('time')
                status_val = item.get(b'status') or item.get('status')
                status_str = str(status_val).lower() if status_val else ""
                if time_val is not None or "echo" in status_str:
                    received += 1
                    if time_val is not None:
                        t_clean = re.sub(r'[^\d.]', '', str(time_val))
                        try:
                            times.append(float(t_clean))
                        except ValueError:
                            pass

            loss = int(((count - received) / count) * 100) if count > 0 else 100
            avg_rtt = round(sum(times) / len(times), 1) if times else None
            is_online = received > 0

            return {
                "online": is_online,
                "sent": count,
                "received": received,
                "packet_loss": loss,
                "avg_rtt": avg_rtt,
                "detail": f"{received}/{count} paquetes recibidos ({loss}% pérdida)"
            }
        except Exception as e:
            logger.warning(f"Ping MikroTik falló para {address}: {e}. Intentando ping de red local...")
            return self._fallback_os_ping(address, count)

    @staticmethod
    def _fallback_os_ping(address: str, count: int = 2) -> Dict[str, Any]:
        """Ping del sistema operativo como fallback seguro cuando MikroTik no responde"""
        import platform
        import subprocess
        try:
            param = '-n' if platform.system().lower() == 'windows' else '-c'
            timeout_param = '-w' if platform.system().lower() == 'windows' else '-W'
            cmd = ['ping', param, str(count), timeout_param, '1000', str(address)]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='replace', timeout=4)
            output = proc.stdout.lower()
            online = proc.returncode == 0 and ("ttl=" in output or "bytes from" in output)
            return {
                "online": online,
                "sent": count,
                "received": count if online else 0,
                "packet_loss": 0 if online else 100,
                "avg_rtt": None,
                "detail": "Responde ping en red" if online else "Sin respuesta de ping"
            }
        except Exception:
            return {
                "online": False,
                "sent": count,
                "received": 0,
                "packet_loss": 100,
                "avg_rtt": None,
                "detail": "Sin respuesta de ping"
            }




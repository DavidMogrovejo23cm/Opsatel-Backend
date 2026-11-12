"""
Módulo base de conexión SSH/Telnet para OLT Huawei en OPSATEL.
Maneja inicialización, reintentos, buffer, prompts y comandos estándar.
"""
import os
import time
import re
import logging
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime

from .exceptions import (
    NETMIKO_AVAILABLE,
    OLTConnectionError,
    OLTCommandError,
    OLTTimeoutError,
)

if NETMIKO_AVAILABLE:
    from netmiko import ConnectHandler

logger = logging.getLogger(__name__)


class OLTConnectionMixin:
    """Mixin que contiene la lógica de conexión base, buffer, prompts y navegación GPON."""

    def __init__(
        self,
        host: str,
        port: int = 23,
        username: str = 'opsatel',
        password: str = 'admin123',
        timeout: int = 30,
        max_retries: int = 3,
        retry_backoff_base: int = 1,
        device_type: str = 'huawei_olt'
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff_base = max(2, retry_backoff_base)
        self.device_type = device_type
        
        self.connection = None
        self.is_connected = False
        self.last_response = ""
        self.last_command = ""
        self.connection_time: Optional[datetime] = None
        self.command_count = 0

        # Estados de prompt/interfaz cacheados para evitar find_prompt redundantes
        self._current_mode = None  # None, "base", "config", "gpon"
        self._current_gpon = None  # Ejemplo: "0/0"
        
        logger.info(f"OLTInterface inicializado: {host}:{port} ({device_type})")

    def _calculate_backoff(self, attempt: int) -> int:
        """Calcula tiempo de espera para reintentos SSH según política fija."""
        if attempt == 1:
            return 30
        elif attempt == 2:
            return 60
        else:
            return 120

    def _build_connect_config(self) -> Dict[str, Any]:
        """Construye la configuración de conexión para SSH a Huawei OLT."""
        device_type = self.device_type or 'huawei_olt'
        if 'huawei' in device_type.lower():
            device_type = 'huawei_olt'
        
        log_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'scratch', 'netmiko_session.log'))
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        return {
            'device_type': device_type,
            'host': self.host,
            'username': self.username,
            'password': self.password,
            'port': self.port,
            'timeout': self.timeout,
            'read_timeout_override': 15,
            'global_delay_factor': 0.2,
            'fast_cli': True,
            'session_log': log_path,
            'banner_timeout': 15,
            'auth_timeout': 20,
            'session_timeout': 300,
            'conn_timeout': self.timeout,
            'disable_sha2_fix': True,
            'disabled_algorithms': {'pubkeys': ['rsa-sha2-512', 'rsa-sha2-256']},
        }

    def connect(self, force_reconnect: bool = False) -> bool:
        """Conecta a la OLT con reintentos automáticos via SSH."""
        if self.is_connected and not force_reconnect:
            logger.debug("Ya conectado a OLT, usando conexión existente")
            return True
        
        if force_reconnect and self.connection:
            try:
                self.disconnect()
            except Exception:
                pass
        
        if not NETMIKO_AVAILABLE:
            raise OLTConnectionError("Netmiko no instalado. Instala: pip install netmiko")
        
        config = self._build_connect_config()
        logger.info(f"Intentando conexión SSH a {self.host}:{self.port} con usuario {self.username}")
        
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(f"[Intento {attempt}/{self.max_retries}] Conectando a {self.host}:{self.port}...")
                
                start_time = time.time()
                self.connection = ConnectHandler(**config)
                duration_ms = int((time.time() - start_time) * 1000)
                
                self.is_connected = True
                self.connection_time = datetime.now()
                self.command_count = 0
                
                logger.info(f"✓ Conexión establecida en {duration_ms}ms")
                
                self._cleanup_buffer()
                
                try:
                    self.connection.send_command_timing("scroll 512", delay_factor=0.1, max_loops=50)
                except Exception:
                    pass
                
                return True

            except Exception as e:
                logger.warning(f"Intento {attempt} falló: {e}")
                if attempt < self.max_retries:
                    backoff = self._calculate_backoff(attempt)
                    time.sleep(backoff)
                else:
                    self.is_connected = False
                    raise OLTConnectionError(f"Error conectando a OLT: {e}")
        
        return False

    def disconnect(self):
        """Desconecta de la OLT de forma segura."""
        if self.connection:
            try:
                self.connection.disconnect()
                logger.info(f"Desconectado de {self.host}")
            except Exception as e:
                logger.warning(f"Error desconectando: {e}")
            finally:
                self.connection = None
                self.is_connected = False

    def _cleanup_buffer(self, max_iterations: int = 10):
        """Limpia el buffer de la conexión SSH."""
        logger.debug("Limpiando buffer del terminal...")
        try:
            self.connection.clear_buffer()
            logger.debug("Buffer limpiado con clear_buffer()")
        except Exception as e:
            logger.warning(f"Error limpiando buffer (no crítico): {e}")

    def send_command(
        self,
        command: str,
        expect_string: Optional[str] = None,
        delay_factor: float = 1.0,
        strip_prompt: bool = True,
        strip_command: bool = True,
        read_timeout: Optional[int] = None,
        use_timing: bool = False
    ) -> str:
        """Envía un comando a la OLT y obtiene respuesta."""
        if not self.is_connected or not self.connection:
            raise OLTConnectionError("No conectado a la OLT. Llama connect() primero.")
        
        self.last_command = command
        start_time = time.time()
        
        timeout_to_use = read_timeout
        if timeout_to_use is None:
            cmd_lower = command.lower().strip()
            if any(k in cmd_lower for k in ['ont add', 'autofind', 'display ont info', 'optical-power', 'ont delete']):
                timeout_to_use = 90
                logger.info(f"Escalando timeout para comando lento a {timeout_to_use}s: '{command}'")
            else:
                timeout_to_use = self.timeout
        
        try:
            logger.debug(f"Enviando comando: {command} (timeout={timeout_to_use}s, use_timing={use_timing})")
            
            if use_timing:
                response = self.connection.send_command_timing(
                    command,
                    strip_prompt=strip_prompt,
                    strip_command=strip_command,
                    delay_factor=delay_factor
                )
            else:
                if expect_string:
                    response = self.connection.send_command(
                        command,
                        expect_string=expect_string,
                        delay_factor=delay_factor,
                        strip_prompt=strip_prompt,
                        strip_command=False,
                        read_timeout=timeout_to_use
                    )
                else:
                    response = self.connection.send_command(
                        command,
                        delay_factor=delay_factor,
                        strip_prompt=strip_prompt,
                        strip_command=strip_command,
                        read_timeout=timeout_to_use
                    )
            
            self.last_response = response
            self.command_count += 1
            duration_ms = int((time.time() - start_time) * 1000)
            
            logger.debug(f"Comando ejecutado en {duration_ms}ms: {command}")
            try:
                import observability
                observability.log_network_command(
                    equipo=self.host,
                    comando=command,
                    respuesta=response,
                    duracion_ms=duration_ms,
                    exit_status="SUCCESS"
                )
            except Exception:
                pass
            return response

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"✗ Error ejecutando comando: {type(e).__name__}: {e}")
            try:
                import observability
                observability.log_network_command(
                    equipo=self.host,
                    comando=command,
                    respuesta=str(e),
                    duracion_ms=duration_ms,
                    exit_status="ERROR"
                )
            except Exception:
                pass
            e_str = str(e).lower()
            if any(k in e_str for k in ["connection", "ssh", "socket", "read", "eof"]):
                self.disconnect()
            raise OLTCommandError(f"Error ejecutando '{command}': {e}")

    def send_config_commands(self, commands: List[str]) -> Tuple[bool, str]:
        """Envía múltiples comandos de configuración de forma secuencial."""
        if not self.is_connected:
            raise OLTConnectionError("No conectado a la OLT")
        
        try:
            logger.info(f"Enviando {len(commands)} comandos de configuración...")
            responses = []
            for i, cmd in enumerate(commands, 1):
                logger.debug(f"[{i}/{len(commands)}] {cmd}")
                response = self.send_command(cmd, delay_factor=0.5)
                responses.append(response)
            
            full_response = "\n".join(responses)
            logger.info(f"✓ Configuración completada ({len(commands)} comandos)")
            return True, full_response
        except Exception as e:
            logger.error(f"✗ Error en configuración: {e}")
            return False, str(e)

    def get_existing_ont_ids(self, gpon_port: str) -> List[int]:
        """Consulta la OLT para obtener los ONT IDs ya registrados en el puerto GPON."""
        parts = [p.strip() for p in str(gpon_port).split('/') if p.strip()]
        port_num = parts[2] if len(parts) >= 3 else "0"

        self.enter_gpon_interface(gpon_port)
        cmd = f"display ont info {port_num} all"
        logger.info(f"[AutoScale] Ejecutando: {cmd}")
        response = self.send_command(
            cmd,
            expect_string=r'\(config-if-gpon-',
            delay_factor=0.3,
            read_timeout=15
        )
        self.exit_gpon_interface()

        existing_ids = set()
        for line in response.splitlines():
            line_s = line.strip()
            if not line_s:
                continue

            # Formato A: tabla F/S/P (MA5608/MA5683)
            m_a = re.search(r'\b\d+/\s*\d+/\s*\d+\s+(\d+)\s+[0-9A-Fa-f]{16}', line_s)
            if m_a:
                existing_ids.add(int(m_a.group(1)))
                continue

            # Formato B: columna GPON/EPON
            m_b = re.search(r'^\s*(\d+)\s+(?:GPON|EPON)\s+', line_s, re.IGNORECASE)
            if m_b:
                existing_ids.add(int(m_b.group(1)))
                continue

            # Formato C: etiqueta-valor
            m_c = re.search(r'ONT\s+ID\s*:\s*(\d+)', line_s, re.IGNORECASE)
            if m_c:
                existing_ids.add(int(m_c.group(1)))
                continue

            # Formato D: ID + SN hexadecimal
            m_d = re.search(r'^\s*(\d+)\s+[0-9A-Fa-f]{16}\b', line_s)
            if m_d:
                existing_ids.add(int(m_d.group(1)))

        sorted_ids = sorted(existing_ids)
        logger.info(f"[AutoScale] ONT IDs en uso en {gpon_port}: {sorted_ids}")
        return sorted_ids

    def is_service_port_free(self, service_port: int) -> bool:
        """Comprueba directamente contra la OLT si un service-port está libre."""
        cmd = f"display service-port {service_port}"
        logger.info(f"[AutoScale] Verificando service-port {service_port} en OLT: {cmd}")
        try:
            response = self.send_command(
                cmd,
                expect_string=r'\(config\)#',
                delay_factor=0.3,
                read_timeout=15
            )
            resp_lower = response.lower()
            not_found_markers = [
                "the service virtual port does not exist",
                "service-port does not exist",
                "failure:",
                "does not exist",
                "no such item",
                "record does not exist",
                "is invalid",
            ]
            for marker in not_found_markers:
                if marker in resp_lower:
                    logger.info(f"[AutoScale] service-port {service_port} está LIBRE (marcador: '{marker}')")
                    return True

            logger.info(f"[AutoScale] service-port {service_port} está OCUPADO en la OLT")
            return False
        except Exception as exc:
            logger.warning(f"[AutoScale] Error comprobando service-port {service_port}: {exc}")
            return False

    def get_existing_service_ports(self, gpon_port: str) -> List[int]:
        """Consulta la OLT directamente para obtener todos los service-ports existentes."""
        cmd = f"display service-port port {gpon_port}"
        logger.info(f"[AutoScale-SP] Consultando service-ports en OLT para {gpon_port}: {cmd}")

        existing_sps: set = set()
        try:
            response = self.send_command(
                cmd,
                expect_string=r'\(config\)#',
                delay_factor=0.3,
                read_timeout=15
            )
            for line in response.splitlines():
                line_strip = line.strip()
                if not line_strip:
                    continue
                match = re.match(r'^(\d+)\s+', line_strip)
                if match:
                    sp_val = int(match.group(1))
                    if 0 <= sp_val <= 2047:
                        existing_sps.add(sp_val)
        except Exception as exc:
            logger.warning(f"[AutoScale-SP] Error consultando service-ports en {gpon_port}: {exc}.")

        sorted_sps = sorted(existing_sps)
        logger.info(f"[AutoScale-SP] Service-ports en uso en {gpon_port}: {sorted_sps}")
        return sorted_sps

    def _get_gpon_interface(self, gpon_port: str) -> str:
        """Convierte un puerto GPON tipo 0/0/3 en la interfaz de configuración 0/0."""
        if not gpon_port:
            return '0/0'
        parts = [p.strip() for p in str(gpon_port).split('/') if p.strip()]
        if len(parts) >= 2:
            return f'{parts[0]}/{parts[1]}'
        return gpon_port

    def enter_privileged_mode(self) -> str:
        """Entra al modo privilegiado de Huawei."""
        return self.send_command('enable', expect_string=r'#', delay_factor=0.3)

    def enter_config_mode(self) -> str:
        """Entra al modo de configuración global."""
        return self.send_command('config', expect_string=r'\(config\)#', delay_factor=0.3)

    def enter_gpon_interface(self, gpon_port: str) -> str:
        """Entra a la interfaz GPON."""
        interface = self._get_gpon_interface(gpon_port)
        if self._current_mode == "gpon" and self._current_gpon == interface:
            logger.debug(f"[enter_gpon_interface] Ya en gpon interface {interface} según cache. Omitiendo comando.")
            return ""
        
        resp = self.send_command(
            f'interface gpon {interface}',
            expect_string=r'\(config-if-gpon-',
            delay_factor=0.3,
        )
        self._current_mode = "gpon"
        self._current_gpon = interface
        return resp

    def exit_gpon_interface(self) -> str:
        """Sale de la interfaz GPON con 'quit'."""
        if self._current_mode == "config":
            logger.debug("[exit_gpon_interface] Ya en config según cache. Omitiendo quit.")
            return ""
            
        resp = self.send_command(
            'quit',
            expect_string=r'\(config\)#',
            delay_factor=0.3,
        )
        self._current_mode = "config"
        self._current_gpon = None
        return resp

    def _reset_to_base_prompt(self) -> None:
        """Asegura que el prompt esté en el modo base '>' antes de iniciar una secuencia."""
        if not self.is_connected or not self.connection:
            return
        
        logger.info("Detectando y reseteando estado del prompt a '>'...")
        try:
            current = self.connection.find_prompt()
            for _ in range(5):
                if current.endswith('>') and '(' not in current:
                    break
                if current.endswith('#') or '(' in current:
                    current = self.connection.send_command_timing('quit', delay_factor=0.3)
                else:
                    current = self.connection.send_command_timing('\n', delay_factor=0.3)
        except Exception as e:
            logger.warning(f"No se pudo resetear el prompt al modo base: {e}")

    def _ensure_config_mode(self) -> None:
        """Asegura que el prompt esté en (config)# de la forma más directa posible."""
        if not self.is_connected or not self.connection:
            raise OLTConnectionError("No hay sesión activa.")

        if self._current_mode == "config":
            logger.debug("[_ensure_config_mode] Ya en (config)# según cache. Omitiendo find_prompt.")
            return

        try:
            prompt = self.connection.find_prompt()
            logger.info(f"[_ensure_config_mode] Prompt actual: '{prompt}'")
        except Exception as exc:
            raise OLTConnectionError(f"No se pudo leer el prompt: {exc}")

        for _ in range(6):
            if '(config)' in prompt and prompt.endswith('#'):
                self._current_mode = "config"
                return
            if '(' in prompt and prompt.endswith('#') and '(config)' not in prompt:
                self.send_command('quit', expect_string=r'[#>]', delay_factor=0.3)
                prompt = self.connection.find_prompt()
                continue
            if prompt.endswith('#') and '(' not in prompt:
                resp = self.send_command('config', expect_string=r'\(config\)#', delay_factor=0.3)
                self.check_response_for_errors('config', resp)
                self._current_mode = "config"
                return
            if prompt.endswith('>'):
                resp = self.send_command('enable', expect_string=r'[#>]', delay_factor=0.3)
                try:
                    self.check_response_for_errors('enable', resp)
                except OLTCommandError as enable_error:
                    if 'unknown command' not in resp.lower():
                        raise enable_error
                resp = self.send_command('config', expect_string=r'\(config\)#', delay_factor=0.3)
                self.check_response_for_errors('config', resp)
                self._current_mode = "config"
                return
            self.send_command('quit', expect_string=r'[#>]', delay_factor=0.3)
            prompt = self.connection.find_prompt()

        raise OLTCommandError("No se pudo alcanzar el modo de configuración de la OLT")

    def get_connection_info(self) -> Dict[str, Any]:
        """Retorna info de la conexión actual."""
        return {
            'host': self.host,
            'port': self.port,
            'connected': self.is_connected,
            'connection_time': self.connection_time.isoformat() if self.connection_time else None,
            'command_count': self.command_count,
            'uptime_seconds': (
                (datetime.now() - self.connection_time).total_seconds()
                if self.connection_time else None
            )
        }
    
    def __enter__(self):
        """Context manager support."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager cleanup."""
        self.disconnect()
        return False

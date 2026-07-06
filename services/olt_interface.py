"""
OPSATEL ISP - OLT Interface
===========================
Módulo para comunicación con OLT Huawei vía Telnet.
Implementa reintentos, buffer cleanup, parseo de respuestas.

Autor: Arquitecto de Software Senior
Versión: 1.0.0
"""

import logging
import time
import re
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime, timedelta
from decimal import Decimal

try:
    # pyrefly: ignore [missing-import]
    from netmiko import ConnectHandler, NetmikoAuthenticationException, NetmikoTimeoutException
    NETMIKO_AVAILABLE = True
except ImportError:
    NETMIKO_AVAILABLE = False
    logging.warning("Netmiko no instalado. Instala: pip install netmiko")

logger = logging.getLogger(__name__)

# ============================================================================
# EXCEPCIONES PERSONALIZADAS
# ============================================================================

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

# ============================================================================
# CONFIGURACIÓN ESPECÍFICA PARA HUAWEI OLT
# ============================================================================

HUAWEI_OLT_CONFIG = {
    'device_type': 'huawei',  # Netmiko type para Huawei OLT
    'fast_cli': True,  # Modo rápido para terminal
    'session_log': None,  # Puede ser un archivo para debugging
    'global_delay_factor': 1.5,  # Factor de delay para operaciones
    'banner_timeout': 15,  # Timeout banner inicial
    'read_timeout_override': 60,  # Timeout para lectura
}

# Prompts esperados de Huawei OLT (pueden variar según versión)
HUAWEI_PROMPTS = [
    r'.*>$',           # Main prompt
    r'.*#$',           # Config prompt
    r'.*\(config\)#$', # Config submenu
    r'.*\(ont\)#$',    # ONT menu
]

# ============================================================================
# CLASE PRINCIPAL: OLTInterface
# ============================================================================

class OLTInterface:
    """
    Interfaz de conexión a OLT Huawei.
    Maneja Telnet, reintentos, buffer cleanup, parsing.
    """
    
    def __init__(
        self,
        host: str,
        port: int = 23,
        username: str = 'admin',
        password: str = 'admin',
        timeout: int = 30,
        max_retries: int = 3,
        retry_backoff_base: int = 1,
        device_type: str = 'huawei_olt'
    ):
        """
        Inicializa la conexión a la OLT.
        
        Args:
            host: IP de la OLT
            port: Puerto Telnet (default 23)
            username: Usuario de acceso
            password: Contraseña
            timeout: Timeout en segundos
            max_retries: Máximo de reintentos
            retry_backoff_base: Base para exponential backoff
            device_type: Tipo de dispositivo (huawei_olt, zte_olt, etc.)
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff_base = retry_backoff_base
        self.device_type = device_type
        
        self.connection = None
        self.is_connected = False
        self.last_response = ""
        self.last_command = ""
        self.connection_time: Optional[datetime] = None
        self.command_count = 0
        
        logger.info(f"OLTInterface inicializado: {host}:{port} ({device_type})")
    
    def _calculate_backoff(self, attempt: int) -> int:
        """
        Calcula tiempo de espera con exponential backoff.
        Ejemplo: base=1, attempt=1 → 1s, attempt=2 → 2s, attempt=3 → 4s
        
        Args:
            attempt: Número de intento (1-based)
            
        Returns:
            Tiempo de espera en segundos
        """
        backoff_seconds = self.retry_backoff_base * (2 ** (attempt - 1))
        # Cap máximo de 30 segundos
        backoff_seconds = min(backoff_seconds, 30)
        return backoff_seconds
    
    def _build_connect_config(self) -> Dict[str, Any]:
        """Construye la configuración de conexión para SSH a Huawei OLT."""
        device_type = self.device_type or 'huawei_olt'
        if 'huawei' in device_type.lower():
            device_type = 'huawei_olt'
        return {
            'device_type': device_type,
            'host': self.host,
            'username': self.username,
            'password': self.password,
            'port': self.port,
            'timeout': self.timeout,
            'read_timeout_override': self.timeout,
            'global_delay_factor': 1.5,
            'fast_cli': True,
            'session_log': None,
            'banner_timeout': 15,
            'auth_timeout': 20,
            'session_timeout': 60,
            'conn_timeout': self.timeout,
        }

    def connect(self, force_reconnect: bool = False) -> bool:
        """
        Conecta a la OLT con reintentos automáticos via SSH.
        
        Args:
            force_reconnect: Forzar reconexión si ya está conectado
            
        Returns:
            True si conexión exitosa, False si falla después de reintentos
        """
        if self.is_connected and not force_reconnect:
            logger.debug("Ya conectado a OLT, usando conexión existente")
            return True
        
        if self.connection:
            try:
                self.disconnect()
            except:
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
                
                # Limpiar buffer inicial
                self._cleanup_buffer()
                
                return True
                
            except (NetmikoAuthenticationException, NetmikoTimeoutException) as e:
                logger.warning(f"[Intento {attempt}] Error de conexión: {e}")
                
                if attempt < self.max_retries:
                    backoff = self._calculate_backoff(attempt)
                    logger.info(f"Esperando {backoff}s antes de reintentar...")
                    time.sleep(backoff)
                else:
                    logger.error(f"✗ Fallo conexión a OLT después de {self.max_retries} intentos")
                    self.is_connected = False
                    raise OLTConnectionError(f"No se puede conectar a {self.host}:{self.port}: {e}")
            
            except Exception as e:
                logger.error(f"[Intento {attempt}] Error inesperado: {type(e).__name__}: {e}")
                if attempt < self.max_retries:
                    backoff = self._calculate_backoff(attempt)
                    time.sleep(backoff)
                else:
                    self.is_connected = False
                    raise OLTConnectionError(f"Error conectando a OLT: {e}")
        
        return False
    
    def disconnect(self):
        """Desconecta de la OLT de forma segura"""
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
        """
        Limpia el buffer de la conexión Telnet.
        Esto es crítico para sincronizar con el prompt correcto.
        
        Args:
            max_iterations: Máximo de iteraciones para evitar bucles infinitos
        """
        logger.debug("Limpiando buffer del terminal...")
        
        try:
            for i in range(max_iterations):
                try:
                    # Intentar leer lo que hay sin esperar
                    output = self.connection.read_very_eager()
                    
                    if not output:
                        logger.debug(f"Buffer limpio después de {i} iteraciones")
                        return
                    
                    logger.debug(f"Buffer garbage {i}: {output[:100]}")
                    time.sleep(0.1)
                
                except EOFError:
                    logger.debug("Buffer limpio (EOFError)")
                    return
            
            logger.warning("Buffer cleanup alcanzó iteraciones máximas")
        
        except Exception as e:
            logger.warning(f"Error limpiando buffer: {e}")
    
    def send_command(
        self,
        command: str,
        expect_string: Optional[str] = None,
        delay_factor: float = 1.0,
        strip_prompt: bool = True,
        strip_command: bool = True
    ) -> str:
        """
        Envía un comando a la OLT y obtiene respuesta.
        
        Args:
            command: Comando a enviar
            expect_string: String adicional a esperar (default: prompt estándar)
            delay_factor: Factor de delay adicional
            strip_prompt: Remover prompt de la respuesta
            strip_command: Remover echo del comando
            
        Returns:
            Respuesta de la OLT (limpia)
            
        Raises:
            OLTCommandError: Si hay error ejecutando comando
        """
        if not self.is_connected or not self.connection:
            raise OLTConnectionError("No conectado a la OLT. Llama connect() primero.")
        
        self.last_command = command
        start_time = time.time()
        
        try:
            logger.debug(f"Enviando comando: {command}")
            
            # Enviar comando
            if expect_string:
                response = self.connection.send_command(
                    command,
                    expect_string=expect_string,
                    strip_prompt=strip_prompt,
                    strip_command=strip_command,
                    delay_factor=delay_factor,
                    read_timeout=self.timeout
                )
            else:
                response = self.connection.send_command(
                    command,
                    strip_prompt=strip_prompt,
                    strip_command=strip_command,
                    delay_factor=delay_factor,
                    read_timeout=self.timeout
                )
            
            duration_ms = int((time.time() - start_time) * 1000)
            self.last_response = response
            self.command_count += 1
            
            logger.debug(f"✓ Comando completado en {duration_ms}ms. Respuesta: {response[:200]}...")
            
            return response
        
        except NetmikoTimeoutException as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"✗ Timeout esperando respuesta ({duration_ms}ms): {e}")
            raise OLTTimeoutError(f"Timeout en comando: {command}")
        
        except Exception as e:
            logger.error(f"✗ Error ejecutando comando: {type(e).__name__}: {e}")
            raise OLTCommandError(f"Error ejecutando '{command}': {e}")
    
    def send_config_commands(self, commands: List[str]) -> Tuple[bool, str]:
        """
        Envía múltiples comandos de configuración de forma secuencial.
        
        Args:
            commands: Lista de comandos
            
        Returns:
            Tupla (exitoso, respuesta_concatenada)
        """
        if not self.is_connected:
            raise OLTConnectionError("No conectado a la OLT")
        
        try:
            logger.info(f"Enviando {len(commands)} comandos de configuración...")
            
            responses = []
            for i, cmd in enumerate(commands, 1):
                logger.debug(f"[{i}/{len(commands)}] {cmd}")
                response = self.send_command(cmd, delay_factor=1.5)
                responses.append(response)
                
                # Pequeño delay entre comandos
                time.sleep(0.2)
            
            full_response = "\n".join(responses)
            logger.info(f"✓ Configuración completada ({len(commands)} comandos)")
            
            return True, full_response
        
        except Exception as e:
            logger.error(f"✗ Error en configuración: {e}")
            return False, str(e)

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
        return self.send_command('enable', delay_factor=1.2)

    def enter_config_mode(self) -> str:
        """Entra al modo de configuración global."""
        return self.send_command('config', delay_factor=1.2)

    def enter_gpon_interface(self, gpon_port: str) -> str:
        """Entra a la interfaz GPON correspondiente (ej. 0/0 o 0/1)."""
        interface = self._get_gpon_interface(gpon_port)
        return self.send_command(f'interface gpon {interface}', delay_factor=1.2)

    def build_activation_commands(self, payload: Dict[str, Any]) -> List[str]:
        """Construye la secuencia de comandos Huawei para activar un ONT."""
        gpon_port = payload.get('gpon_port', '0/0/0')
        ont_id = payload.get('ont_id', '0')
        mac = payload.get('mac', '000000000000')
        description = payload.get('description', f'ONT_{ont_id}')
        profile_id = payload.get('profile_id', '100')
        srvprofile_id = payload.get('srvprofile_id', profile_id)
        service_port = payload.get('service_port', str(int(ont_id) + 1000))
        vlan = payload.get('vlan', payload.get('user_vlan', profile_id))
        user_vlan = payload.get('user_vlan', vlan)

        # Extraer slot/port e interface
        parts = [p.strip() for p in str(gpon_port).split('/') if p.strip()]
        if len(parts) >= 3:
            interface = f"{parts[0]}/{parts[1]}"
            port_num = parts[2]
        else:
            interface = "0/0"
            port_num = "0"

        return [
            f"interface gpon {interface}",
            f'ont add {port_num} {ont_id} sn-auth "{mac}" omci ont-lineprofile-id {profile_id} ont-srvprofile-id {srvprofile_id} desc "{description}"',
            f'ont port native-vlan {port_num} {ont_id} eth 1 vlan {vlan} priority 0',
            "quit",
            f'service-port {service_port} vlan {vlan} gpon {gpon_port} ont {ont_id} gemport {profile_id} multi-service user-vlan {user_vlan} tag-transform translate',
        ]

    def execute_activation_sequence(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta el flujo completo de activación: enable -> config -> interface gpon -> comandos ONT."""
        try:
            self.connect()
            responses = []

            responses.append(('enable', self.enter_privileged_mode()))
            responses.append(('config', self.enter_config_mode()))
            responses.append(('interface', self.enter_gpon_interface(payload.get('gpon_port', '0/0/0'))))

            for command in self.build_activation_commands(payload):
                responses.append((command, self.send_command(command, delay_factor=1.5)))

            return {
                'success': True,
                'commands': [cmd for cmd, _ in responses],
                'responses': [resp for _, resp in responses],
            }
        except Exception as e:
            logger.error(f"Error en execute_activation_sequence: {e}")
            return {
                'success': False,
                'error': str(e),
                'commands': [],
                'responses': [],
            }
    
    def parse_ont_power(self, response: str) -> Optional[float]:
        """
        Parsea respuesta de 'display ont info' para extraer potencia RX.
        Respuesta típica Huawei:
        
        ONT power: RX power(dBm): -23.45
        o
        Rx power(dBm): -23.45
        
        Args:
            response: Respuesta cruda de la OLT
            
        Returns:
            Valor de potencia en dBm o None si no se encuentra
        """
        try:
            # Intentar varios patrones
            patterns = [
                r'RX power\(dBm\):\s*([-\d.]+)',
                r'Rx power\(dBm\):\s*([-\d.]+)',
                r'RXpower\(dBm\):\s*([-\d.]+)',
                r'(?:RX|Rx) ?power.*?\:\s*([-\d.]+)',
                r'Current.*?power.*?([-\d.]+)',
                r'Optical.*?power.*?([-\d.]+)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, response, re.IGNORECASE)
                if match:
                    power_str = match.group(1).strip()
                    power_val = float(power_str)
                    logger.debug(f"Potencia parseada: {power_val} dBm")
                    return power_val
            
            logger.warning(f"No se encontró potencia en respuesta. Raw: {response[:200]}")
            return None
        
        except Exception as e:
            logger.error(f"Error parseando potencia: {e}")
            return None
    
    def parse_ont_status(self, response: str) -> Optional[str]:
        """
        Parsea estado de ONT de respuesta de 'display ont info'.
        Estados típicos: online, offline, working, etc.
        
        Args:
            response: Respuesta cruda de la OLT
            
        Returns:
            Estado de ONT o None si no se encuentra
        """
        try:
            patterns = [
                r'ONT state:\s*(\w+)',
                r'State:\s*(\w+)',
                r'(?:Current )?Status:\s*(\w+)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, response, re.IGNORECASE)
                if match:
                    status = match.group(1).strip().lower()
                    logger.debug(f"Estado ONT parseado: {status}")
                    return status
            
            return None
        
        except Exception as e:
            logger.error(f"Error parseando estado: {e}")
            return None

    def parse_autofind_output(self, response: str) -> list:
        """
        Parsea la salida de 'display ont autofind all' para obtener ONTs pendientes.
        """
        lines = response.splitlines()
        candidates = []
        for line in lines:
            if not line.strip():
                continue
            if any(header in line for header in ('Port', 'ONT', '-----', 'Total', 'Number', 'OLT')):
                continue

            # Buscar puerto GPON y ont-id en cualquier parte de la línea
            match_port = re.search(r'(\d+/\d+/\d+)\s+(\d+)', line)
            if not match_port:
                continue

            gpon_port = match_port.group(1).strip()
            ont_id = match_port.group(2).strip()

            # Buscar MAC o GPON SN en la línea
            mac_match = re.search(r'([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}|[0-9A-Fa-f]{16}|[A-Za-z]{4}[0-9A-Fa-f]{8}|[0-9A-Fa-f]{12}', line)
            mac = mac_match.group(0).upper() if mac_match else None
            
            # Normalizar MAC si es de 12 caracteres (con o sin separadores)
            if mac:
                mac_clean = mac.replace('-', '').replace(':', '').replace('.', '')
                is_hex = all(c in '0123456789ABCDEF' for c in mac_clean)
                if len(mac_clean) == 12 and is_hex:
                    mac = ':'.join(mac_clean[i:i+2] for i in range(0, 12, 2))
                else:
                    mac = mac_clean  # Dejar como GPON SN continuo (ej: HWTC12345678 o 48575443B0C1D2E3)

            # Buscar estado o texto de activación
            status_match = re.search(r'(?i)(pending|not activated|not-activated|inactive|activated|online|offline|error|unknown)', line)
            status = status_match.group(0).lower() if status_match else None

            candidates.append({
                'gpon_port': gpon_port,
                'ont_id': ont_id,
                'mac': mac,
                'status': status,
                'raw': line.strip()
            })
        return candidates

    def display_autofind_all(self) -> list:
        """
        Ejecuta 'display ont autofind all' para listar ONTs detectadas por la OLT.
        """
        try:
            self.enter_privileged_mode()
            self.enter_config_mode()
        except Exception as e:
            logger.warning(f"No se pudo entrar a modo privilegiado/config para autofind: {e}")
        response = self.send_command('display ont autofind all', delay_factor=2.0)
        candidates = self.parse_autofind_output(response)
        return candidates
    
    def check_ont_power(self, gpon_port: str, ont_id: str) -> Dict[str, Any]:
        """
        Verifica la potencia de un ONT específico.
        
        Args:
            gpon_port: Puerto GPON (ej: "0/0/1")
            ont_id: ID de ONT (ej: "1")
            
        Returns:
            Diccionario con {'power': float, 'status': str, 'response': str}
        """
        try:
            # Extraer slot/port e interface
            parts = [p.strip() for p in str(gpon_port).split('/') if p.strip()]
            if len(parts) >= 3:
                interface = f"{parts[0]}/{parts[1]}"
                port_num = parts[2]
            else:
                interface = "0/0"
                port_num = "0"

            logger.info(f"Verificando potencia ONT {gpon_port} {ont_id}...")
            
            # Entrar a la interfaz gpon correspondiente
            try:
                self.enter_privileged_mode()
                self.enter_config_mode()
                self.send_command(f"interface gpon {interface}", delay_factor=1.2)
            except Exception as nav_err:
                logger.warning(f"Error navegando a interfaz gpon para verificar potencia: {nav_err}")

            commands = [
                f"display ont optical-info {port_num} {ont_id}",
                f"display ont info {port_num} {ont_id}",
            ]
            
            last_response = ""
            for command in commands:
                try:
                    response = self.send_command(command, delay_factor=2.0)
                    last_response = response
                    power = self.parse_ont_power(response)
                    status = self.parse_ont_status(response)
                    
                    if power is not None:
                        # Salir de la interfaz GPON
                        try:
                            self.send_command("quit", delay_factor=1.0)
                        except:
                            pass
                        return {
                            'power': power,
                            'status': status,
                            'response': response,
                            'gpon_port': gpon_port,
                            'ont_id': ont_id,
                            'timestamp': datetime.now().isoformat(),
                            'command': command,
                        }
                except Exception as inner_exc:
                    logger.debug(f"Comando {command} falló: {inner_exc}")
                    continue
            
            # Salir de la interfaz GPON
            try:
                self.send_command("quit", delay_factor=1.0)
            except:
                pass

            return {
                'power': None,
                'status': 'unknown',
                'response': last_response,
                'gpon_port': gpon_port,
                'ont_id': ont_id,
                'timestamp': datetime.now().isoformat(),
                'error': 'No se pudo leer potencia con los comandos disponibles',
            }
        
        except Exception as e:
            logger.error(f"Error verificando potencia: {e}")
            return {
                'power': None,
                'status': 'error',
                'response': str(e),
                'gpon_port': gpon_port,
                'ont_id': ont_id,
                'error': str(e)
            }
    
    def get_connection_info(self) -> Dict[str, Any]:
        """Retorna info de la conexión actual"""
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
        """Context manager support"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager cleanup"""
        self.disconnect()
        return False


# ============================================================================
# FUNCIONES DE TESTING
# ============================================================================

def test_olt_interface():
    """Test básico de conexión (requiere OLT real)"""
    print("=" * 60)
    print("TESTING: OLTInterface")
    print("=" * 60)
    
    # Configuración de test (REEMPLAZAR CON IP REAL DE OLT)
    OLT_HOST = "OLT_HOST_BAÑOS"  # ← CAMBIAR POR IP REAL
    OLT_USER = "admin"
    OLT_PASS = "admin123"
    
    print(f"Intentando conectar a {OLT_HOST}...")
    
    try:
        olt = OLTInterface(
            host=OLT_HOST,
            username=OLT_USER,
            password=OLT_PASS,
            timeout=30,
            max_retries=2
        )
        
        # Conectar
        if olt.connect():
            print("✓ Conectado a OLT")
            
            # Ejecutar comando simple
            try:
                response = olt.send_command("display ont info 0/0/1 1")
                print(f"Respuesta: {response[:200]}")
            except Exception as e:
                print(f"Error ejecutando comando: {e}")
            
            # Desconectar
            olt.disconnect()
            print("✓ Desconectado")
        else:
            print("✗ No se pudo conectar")
    
    except Exception as e:
        print(f"✗ Error: {e}")
    
    print("=" * 60)
    print("TEST COMPLETE\n")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Descomenta para testear con OLT real:
    # test_olt_interface()
    
    print("OLTInterface módulo cargado correctamente")

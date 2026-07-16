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

class OLTAlreadyExistsError(OLTCommandError):
    """La entidad (ONT, service-port, etc.) ya existe en la OLT"""
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
        username: str = 'opsatel',
        password: str = 'admin123',
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
        self.retry_backoff_base = max(2, retry_backoff_base)
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
        Calcula tiempo de espera para reintentos SSH según política fija:
          - 1er fallo → 30 segundos de espera
          - 2do fallo → 60 segundos de espera
          - 3er fallo en adelante → 120 segundos de espera (cap permanente)

        Esta política evita saturar el mecanismo anti-lockout de la OLT Huawei.

        Args:
            attempt: Número de intento fallido (1-based)

        Returns:
            Tiempo de espera en segundos
        """
        if attempt == 1:
            return 30
        elif attempt == 2:
            return 60
        else:
            return 120
    
    def _build_connect_config(self) -> Dict[str, Any]:
        """Construye la configuración de conexión para SSH a Huawei OLT."""
        import os
        device_type = self.device_type or 'huawei_olt'
        if 'huawei' in device_type.lower():
            device_type = 'huawei_olt'
        
        # Ruta absoluta para el archivo de log en la carpeta scratch del proyecto
        log_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scratch', 'netmiko_session.log'))
        # Asegurarse de que exista la carpeta scratch
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

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
            'session_log': log_path,
            'banner_timeout': 15,
            'auth_timeout': 20,
            'session_timeout': 300,  # 5 minutos — mantener sesión viva entre tareas
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
        
        # Solo destruir la conexión si se fuerza reconexión o si realmente no está activa.
        # No destruir una sesión viva innecesariamente para evitar múltiples autenticaciones SSH.
        if force_reconnect and self.connection:
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
                
            except NetmikoAuthenticationException as e:
                logger.error(f"✗ Error de autenticación crítico (credenciales inválidas) en {self.host}:{self.port}: {e}")
                self.is_connected = False
                raise OLTConnectionError(f"Error de autenticación: Credenciales inválidas para {self.username} en {self.host}:{self.port}")
                
            except NetmikoTimeoutException as e:
                logger.warning(f"[Intento {attempt}] Timeout de conexión: {e}")
                if attempt < self.max_retries:
                    backoff = self._calculate_backoff(attempt)
                    logger.info(f"Esperando {backoff}s antes de reintentar...")
                    time.sleep(backoff)
                else:
                    logger.error(f"✗ Fallo conexión a OLT por timeout después de {self.max_retries} intentos")
                    self.is_connected = False
                    raise OLTConnectionError(f"No se puede conectar a {self.host}:{self.port} (Timeout): {e}")
            
            except Exception as e:
                logger.error(f"[Intento {attempt}] Error inesperado de conexión: {type(e).__name__}: {e}")
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
        Limpia el buffer de la conexión SSH.
        Usa clear_buffer() de Netmiko (compatible con SSH).
        read_very_eager() era solo para Telnet y lanza AttributeError con SSH.
        
        Args:
            max_iterations: No usado, mantenido por compatibilidad de firma
        """
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
        """
        Envía un comando a la OLT y obtiene respuesta.
        
        Args:
            command: Comando a enviar
            expect_string: String adicional a esperar (default: prompt estándar)
            delay_factor: Factor de delay adicional
            strip_prompt: Remover prompt de la respuesta
            strip_command: Remover echo del comando
            read_timeout: Timeout personalizado en segundos (escalado automático si es None)
            use_timing: Si es True, usa send_command_timing en vez de send_command normal
            
        Returns:
            Respuesta de la OLT (limpia)
            
        Raises:
            OLTCommandError: Si hay error ejecutando comando
        """
        if not self.is_connected or not self.connection:
            raise OLTConnectionError("No conectado a la OLT. Llama connect() primero.")
        
        self.last_command = command
        start_time = time.time()
        
        # Escalado automático de timeout para comandos lentos
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
                # Enviar comando
                if expect_string:
                    response = self.connection.send_command(
                        command,
                        expect_string=expect_string,
                        strip_prompt=strip_prompt,
                        strip_command=strip_command,
                        delay_factor=delay_factor,
                        read_timeout=timeout_to_use
                    )
                else:
                    response = self.connection.send_command(
                        command,
                        strip_prompt=strip_prompt,
                        strip_command=strip_command,
                        delay_factor=delay_factor,
                        read_timeout=timeout_to_use
                    )
            
            # Auto-responder logic for interactive prompts
            if response:
                resp_lower = response.lower()
                if any(q in resp_lower for q in ["are you sure", "y/n", "confirm to", "confirm"]):
                    logger.info("Confirmación interactiva detectada. Enviando 'y'...")
                    response += "\n" + self.connection.send_command_timing(
                        "y",
                        strip_prompt=strip_prompt,
                        strip_command=strip_command,
                        delay_factor=delay_factor
                    )
                elif "}:" in response:
                    logger.info("Indicador interactivo '}:' detectado. Enviando Enter...")
                    response += "\n" + self.connection.send_command_timing(
                        "",
                        strip_prompt=strip_prompt,
                        strip_command=strip_command,
                        delay_factor=delay_factor
                    )
            
            duration_ms = int((time.time() - start_time) * 1000)
            self.last_response = response
            self.command_count += 1
            
            logger.debug(f"✓ Comando completado en {duration_ms}ms. Respuesta: {response[:200]}...")
            
            return response
        
        except NetmikoTimeoutException as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"✗ Timeout esperando respuesta ({duration_ms}ms): {e}")
            self.disconnect()
            raise OLTTimeoutError(f"Timeout en comando: {command}")
        
        except Exception as e:
            logger.error(f"✗ Error ejecutando comando: {type(e).__name__}: {e}")
            # Si es un error de conexión/lectura/SSH, desconectar de forma segura
            e_str = str(e).lower()
            if any(k in e_str for k in ["connection", "ssh", "socket", "read", "eof"]):
                self.disconnect()
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

    def get_existing_ont_ids(self, gpon_port: str) -> List[int]:
        """
        Consulta la OLT para obtener los ONT IDs ya registrados en el puerto GPON especificado.
        
        Args:
            gpon_port: Puerto GPON (ej: "0/0/15")
            
        Returns:
            Lista de ONT IDs existentes (enteros)
        """
        # Extraer slot/port e interface
        parts = [p.strip() for p in str(gpon_port).split('/') if p.strip()]
        if len(parts) >= 3:
            interface = f"{parts[0]}/{parts[1]}"
            port_num = parts[2]
        else:
            interface = "0/0"
            port_num = "0"
            
        # Entrar a la interfaz gpon correspondiente
        # Nota: Asumimos que ya estamos en modo config
        self.enter_gpon_interface(gpon_port)
        
        cmd = f"display ont info {port_num} all"
        logger.info(f"Consultando ONT IDs existentes con comando: {cmd}")
        response = self.send_command(cmd, use_timing=True, delay_factor=1.5)
        
        # Volver a modo config
        self.exit_gpon_interface()
        
        existing_ids = set()
        for line in response.splitlines():
            line_strip = line.strip()
            if not line_strip:
                continue
            
            # Caso 1: Fila de tabla que comienza con el ONT ID (ej: "   0     GPON ...")
            match_table = re.match(r'^(\d+)\b', line_strip)
            if match_table:
                val = int(match_table.group(1))
                if 0 <= val <= 127:
                    existing_ids.add(val)
                    continue
            
            # Caso 2: Formato etiqueta-valor (ej: "ONTID : 1" o "ONT ID: 2")
            match_lbl = re.search(r'(?:ONT\s*ID|ONTID)\s*[:\s]\s*(\d+)', line_strip, re.IGNORECASE)
            if match_lbl:
                val = int(match_lbl.group(1))
                if 0 <= val <= 127:
                    existing_ids.add(val)
                    
        sorted_ids = sorted(list(existing_ids))
        logger.info(f"ONT IDs detectados en GPON {gpon_port}: {sorted_ids}")
        return sorted_ids

    def is_service_port_free(self, service_port: int) -> bool:
        """
        Comprueba si un ID de service-port está libre en la OLT.
        """
        # Nota: Asumimos que ya estamos en modo config o privilegiado
        cmd = f"display service-port {service_port}"
        try:
            response = self.send_command(cmd, use_timing=True, delay_factor=1.2)
            resp_lower = response.lower()
            if "does not exist" in resp_lower or "not exist" in resp_lower:
                return True
            # Si contiene información del service port, no está libre
            if str(service_port) in resp_lower and "vlan" in resp_lower:
                return False
            # Si la OLT da "Failure: ...", dependemos de si dice no existe,
            # pero por seguridad si contiene "failure" o "does not exist", lo consideramos libre
            if "failure" in resp_lower:
                return True
            return False
        except Exception as e:
            logger.warning(f"Error comprobando service-port {service_port}: {e}")
            # Si falla el comando, asumimos que está ocupado para no arriesgar colisión
            return False

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
        return self.send_command('enable', use_timing=True, delay_factor=1.2)

    def enter_config_mode(self) -> str:
        """Entra al modo de configuración global."""
        return self.send_command('config', use_timing=True, delay_factor=1.2)

    def enter_gpon_interface(self, gpon_port: str) -> str:
        """Entra a la interfaz GPON."""
        interface = self._get_gpon_interface(gpon_port)
        return self.send_command(
            f'interface gpon {interface}',
            use_timing=True,
            delay_factor=1.2,
        )

    def exit_gpon_interface(self) -> str:
        """Sale de la interfaz GPON con 'quit'."""
        return self.send_command(
            'quit',
            use_timing=True,
            delay_factor=1.2,
        )

    def build_activation_commands(self, payload: Dict[str, Any]) -> Dict[str, Any]:
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

        # Extraer slot/port e interface
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

        # Calcular valores por defecto basados en el puerto GPON
        derived_profile = str(100 + puerto_val)   # Ej: 108 para puerto 8
        derived_vlan = str(300 + puerto_val)      # Ej: 308 para puerto 8

        # Validar y limpiar profile_id
        profile_id = payload.get('profile_id')
        if not profile_id or not str(profile_id).isdigit():
            profile_id = derived_profile

        # Validar y limpiar srvprofile_id
        srvprofile_id = payload.get('srvprofile_id')
        if not srvprofile_id or not str(srvprofile_id).isdigit():
            srvprofile_id = profile_id

        # Validar y limpiar vlan (VLAN de la OLT para service-port)
        vlan = payload.get('vlan')
        if not vlan or not str(vlan).isdigit():
            vlan = derived_vlan

        # Validar y limpiar user_vlan (VLAN nativa del cliente / traducción)
        user_vlan = payload.get('user_vlan')
        if not user_vlan or not str(user_vlan).isdigit():
            user_vlan = profile_id

        # Validar y limpiar service_port
        service_port = payload.get('service_port')
        if not service_port or not str(service_port).isdigit():
            try:
                ont_val = int(ont_id)
            except ValueError:
                ont_val = 0
            service_port = str(ont_val + 1000)

        # Construir los comandos individuales como strings
        cmd_ont = f'ont add {port_num} {ont_id} sn-auth "{mac}" omci ont-lineprofile-id {profile_id} ont-srvprofile-id {srvprofile_id} desc "{description}"'
        cmd_breach = f'ont port native-vlan {port_num} {ont_id} eth 1 vlan {user_vlan} priority 0'
        cmd_servicio = f'service-port {service_port} vlan {vlan} gpon {gpon_port} ont {ont_id} gemport {profile_id} multi-service user-vlan {user_vlan} tag-transform translate'

        # NOTA: 'interface gpon' y 'quit' NO están aquí.
        # Las transiciones de prompt las gestiona execute_activation_sequence
        # usando enter_gpon_interface() y exit_gpon_interface() con expect_string correcto.
        return {
            'gpon_commands': [
                # Comandos ejecutados DENTRO de (config-if-gpon-X/X)#
                cmd_ont,
                cmd_breach,
            ],
            'config_commands': [
                # Comandos ejecutados DESDE (config)# tras el quit
                cmd_servicio,
            ],
            # Metadatos completos del aprovisionamiento para persistencia en DB
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
                'cmd_breach': cmd_breach,
                'cmd_servicio': cmd_servicio,
            }
        }

    def check_response_for_errors(self, command: str, response: str) -> None:
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
            'exist'
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
                # Si el error es de tipo "ya existe", lanzar OLTAlreadyExistsError
                if any(nf in resp_lower for nf in non_fatal_keywords):
                    logger.warning(f"Entidad ya existente detectada en respuesta a '{command}': {response.strip()}")
                    raise OLTAlreadyExistsError(f"Entidad ya existente: {response.strip()}")
                
                lines = response.split('\n')
                error_line = next((line.strip() for line in lines if kw in line.lower()), response.strip())
                logger.error(f"Error detectado en respuesta al comando '{command}': {error_line}")
                raise OLTCommandError(f"Error OLT en '{command}': {error_line}")

    def _reset_to_base_prompt(self) -> None:
        """
        Asegura que el prompt esté en el modo base '>' antes de iniciar una secuencia.
        Si la sesión SSH ya está en un submodo (como config o config-if),
        envía 'quit' secuencialmente hasta retornar a '>'.
        """
        if not self.is_connected or not self.connection:
            return
        
        logger.info("Detectando y reseteando estado del prompt a '>'...")
        try:
            current = self.connection.find_prompt()
            logger.info(f"Prompt actual detectado: {current}")
            
            for _ in range(5):
                if current.endswith('>') and '(' not in current:
                    logger.info("Prompt ya está en el modo base '>'")
                    break
                
                if current.endswith('#') or '(' in current:
                    logger.info("Prompt en submodo o habilitado. Enviando 'quit'...")
                    current = self.connection.send_command_timing('quit', delay_factor=1.0)
                    logger.info(f"Nuevo prompt: {current}")
                else:
                    current = self.connection.send_command_timing('\n', delay_factor=1.0)
        except Exception as e:
            logger.warning(f"No se pudo resetear el prompt al modo base: {e}")

    def execute_activation_sequence(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta el flujo completo de activación con sincronización explícita de prompts.

        Transiciones de prompt gestionadas:
          >  → enable →  #
          #  → config →  (config)#
          (config)#  → interface gpon →  (config-if-gpon-X/X)#
          (config-if-gpon-X/X)#  → quit →  (config)#
          (config)#  → service-port →  (config)#

        Returns:
            Diccionario enriquecido con todos los datos del aprovisionamiento:
            success, status, message, commands, responses, y todos los campos
            técnicos (port_num, ont_id, service_port, mac, vlan, etc.) listos
            para ser persistidos directamente en el modelo Cliente.

        NOTA: NO llama a self.connect() — la conexión es gestionada externamente.
        """
        responses = []
        already_exists_detected = False
        already_exists_msg = ""
        try:
            if not self.is_connected:
                raise OLTConnectionError("No hay sesión activa. Llama connect() antes de ejecutar secuencias.")

            # Resetear prompt al estado base antes de iniciar
            self._reset_to_base_prompt()

            # 1. Modo Privilegiado  (> → #)
            resp = self.enter_privileged_mode()
            self.check_response_for_errors('enable', resp)
            responses.append(('enable', resp))

            # 2. Modo Configuración  (# → (config)#)
            resp = self.enter_config_mode()
            self.check_response_for_errors('config', resp)
            responses.append(('config', resp))

            # 3. Obtener listas de comandos separadas por contexto
            #    build_activation_commands ahora retorna también 'metadata' con todos
            #    los valores calculados para facilitar la persistencia en DB.
            cmd_groups = self.build_activation_commands(payload)
            gpon_cmds = cmd_groups['gpon_commands']
            config_cmds = cmd_groups['config_commands']
            meta = cmd_groups['metadata']  # Todos los valores calculados

            # 4. Entrar a interfaz GPON  ((config)# → (config-if-gpon-X/X)#)
            resp = self.enter_gpon_interface(payload.get('gpon_port', '0/0/0'))
            self.check_response_for_errors('interface gpon', resp)
            responses.append(('interface gpon', resp))

            # 5. Comandos dentro de (config-if-gpon-X/X)#
            for cmd in gpon_cmds:
                try:
                    resp = self.send_command(
                        cmd,
                        use_timing=True,
                        delay_factor=2.5,  # Delay mayor para comandos interactivos y pesados
                    )
                    self.check_response_for_errors(cmd, resp)
                    responses.append((cmd, resp))
                except OLTAlreadyExistsError as e:
                    logger.warning(f"Advertencia de duplicidad detectada y capturada en '{cmd}': {e}")
                    already_exists_detected = True
                    already_exists_msg = str(e)
                    responses.append((cmd, f"Warning/Already Exists: {e}"))

            # 6. Salir de interfaz GPON  ((config-if-gpon-X/X)# → (config)#)
            resp = self.exit_gpon_interface()
            responses.append(('quit', resp))

            # 7. Comandos desde (config)#  (service-port, etc.)
            for cmd in config_cmds:
                try:
                    resp = self.send_command(
                        cmd,
                        use_timing=True,
                        delay_factor=2.0,
                    )
                    self.check_response_for_errors(cmd, resp)
                    responses.append((cmd, resp))
                except OLTAlreadyExistsError as e:
                    logger.warning(f"Advertencia de duplicidad detectada y capturada en '{cmd}': {e}")
                    already_exists_detected = True
                    already_exists_msg = str(e)
                    responses.append((cmd, f"Warning/Already Exists: {e}"))

            # Base del resultado enriquecido — incluye todos los datos técnicos
            # que el task_processor necesita para persistir en el modelo Cliente.
            enriched_base = {
                'commands': [cmd for cmd, _ in responses],
                'responses': [resp for _, resp in responses],
                # ─── Datos técnicos del aprovisionamiento ───────────────────
                'gpon_port':    meta['gpon_port'],
                'port_num':     meta['port_num'],
                'ont_id':       meta['ont_id'],
                'mac':          meta['mac'],
                'service_port': meta['service_port'],
                'vlan':         meta['vlan'],
                'user_vlan':    meta['user_vlan'],
                'profile_id':   meta['profile_id'],
                'description':  meta['description'],
                # Comandos OLT listos para mostrar al frontend / guardar en DB
                'cmd_ont':      meta['cmd_ont'],
                'cmd_breach':   meta['cmd_breach'],
                'cmd_servicio': meta['cmd_servicio'],
            }

            if already_exists_detected:
                return {
                    **enriched_base,
                    'success': True,
                    'status': 'ALREADY_EXISTS',
                    'message': f"La ONT o parte de la configuración ya existía en la OLT: {already_exists_msg}",
                }

            return {
                **enriched_base,
                'success': True,
                'status': 'SUCCESS',
                'message': 'ONT activada exitosamente en la OLT.',
            }
        except Exception as e:
            logger.error(f"Error en execute_activation_sequence: {e}")
            return {
                'success': False,
                'status': 'ERROR',
                'error': str(e),
                'commands': [cmd for cmd, _ in responses],
                'responses': [resp for _, resp in responses],
            }

    def build_removal_commands(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Construye la secuencia de comandos Huawei para eliminar un ONT.
        
        Secuencia:
          1. (config)# undo service-port <service_port>   -- libera el service-port
          2. interface gpon X/X
          3. (config-if-gpon-X/X)# ont delete <port_num> <ont_id>
        """
        gpon_port = payload.get('gpon_port', '0/0/0')
        ont_id = payload.get('ont_id', '0')
        service_port = str(payload.get('service_port', '')).strip()
        
        # Extraer slot/port e interface
        parts = [p.strip() for p in str(gpon_port).split('/') if p.strip()]
        if len(parts) >= 3:
            port_num = parts[2]
        else:
            port_num = "0"

        # Comandos de config antes de entrar a la interfaz GPON
        config_commands_before = []
        if service_port and service_port.isdigit():
            config_commands_before.append(f"undo service-port {service_port}")
        else:
            logger.warning(f"service_port inválido o vacío ('{service_port}'), se omite undo service-port")

        # 'interface gpon' y 'quit' se gestionan en execute_removal_sequence
        return {
            'config_commands_before': config_commands_before,
            'gpon_commands': [
                f"ont delete {port_num} {ont_id}",
            ],
        }

    def execute_removal_sequence(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta el flujo completo de eliminación con sincronización explícita de prompts.
        
        Secuencia:
          > → enable → #
          # → config → (config)#
          (config)# → undo service-port <sp>      (liberar service-port)
          (config)# → interface gpon X/X → (config-if-gpon-X/X)#
          (config-if-gpon-X/X)# → ont delete <port> <id>
          (config-if-gpon-X/X)# → quit → (config)#
        """
        responses = []
        already_exists_detected = False
        already_exists_msg = ""
        try:
            if not self.is_connected:
                raise OLTConnectionError("No hay sesión activa. Llama connect() antes de ejecutar secuencias.")

            # Resetear prompt al estado base antes de iniciar
            self._reset_to_base_prompt()

            # 1. Modo Privilegiado  (> → #)
            resp = self.enter_privileged_mode()
            self.check_response_for_errors('enable', resp)
            responses.append(('enable', resp))

            # 2. Modo Configuración  (# → (config)#)
            resp = self.enter_config_mode()
            self.check_response_for_errors('config', resp)
            responses.append(('config', resp))

            # 3. Obtener grupos de comandos
            cmd_groups = self.build_removal_commands(payload)

            # 4. Ejecutar undo service-port desde (config)#  ANTES de entrar a la interfaz
            for cmd in cmd_groups.get('config_commands_before', []):
                try:
                    logger.info(f"Ejecutando en (config)#: {cmd}")
                    resp = self.send_command(
                        cmd,
                        use_timing=True,
                        delay_factor=2.0,
                    )
                    self.check_response_for_errors(cmd, resp)
                    responses.append((cmd, resp))
                    logger.info(f"✓ {cmd} ejecutado OK")
                except OLTAlreadyExistsError as e:
                    logger.warning(f"service-port ya eliminado o no existía al ejecutar '{cmd}': {e}")
                    already_exists_detected = True
                    already_exists_msg = str(e)
                    responses.append((cmd, f"Warning/Already removed: {e}"))
                except OLTCommandError as e:
                    # Si el service-port no existe, continuar igual para borrar la ONT
                    logger.warning(f"Error no crítico al ejecutar '{cmd}' (posiblemente ya eliminado): {e}")
                    responses.append((cmd, f"Warning: {e}"))

            # 5. Entrar a interfaz GPON  ((config)# → (config-if-gpon-X/X)#)
            resp = self.enter_gpon_interface(payload.get('gpon_port', '0/0/0'))
            self.check_response_for_errors('interface gpon', resp)
            responses.append(('interface gpon', resp))

            # 6. Comandos dentro de (config-if-gpon-X/X)# (ont delete)
            for cmd in cmd_groups['gpon_commands']:
                try:
                    resp = self.send_command(
                        cmd,
                        use_timing=True,
                        delay_factor=2.0,
                    )
                    self.check_response_for_errors(cmd, resp)
                    responses.append((cmd, resp))
                except OLTAlreadyExistsError as e:
                    logger.warning(f"Advertencia de duplicidad/existente detectada y capturada en '{cmd}': {e}")
                    already_exists_detected = True
                    already_exists_msg = str(e)
                    responses.append((cmd, f"Warning/Already Exists: {e}"))

            # 7. Salir de interfaz GPON  ((config-if-gpon-X/X)# → (config)#)
            resp = self.exit_gpon_interface()
            responses.append(('quit', resp))

            if already_exists_detected:
                return {
                    'success': True,
                    'status': 'ALREADY_EXISTS',
                    'message': f"La ONT o parte de la configuración ya estaba eliminada o no existía: {already_exists_msg}",
                    'commands': [cmd for cmd, _ in responses],
                    'responses': [resp for _, resp in responses],
                }

            return {
                'success': True,
                'status': 'SUCCESS',
                'message': 'ONT y service-port eliminados exitosamente de la OLT.',
                'commands': [cmd for cmd, _ in responses],
                'responses': [resp for _, resp in responses],
            }
        except Exception as e:
            logger.error(f"Error en execute_removal_sequence: {e}")
            return {
                'success': False,
                'status': 'ERROR',
                'error': str(e),
                'commands': [cmd for cmd, _ in responses],
                'responses': [resp for _, resp in responses],
            }

    def build_set_breach_commands(self, payload: Dict[str, Any]) -> List[str]:
        """Construye la secuencia de comandos Huawei para cambiar la VLAN nativa (Bridge)."""
        gpon_port = payload.get('gpon_port', '0/0/0')
        ont_id = payload.get('ont_id', '0')
        priority = payload.get('priority', '0')

        # Extraer slot/port e interface
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

        # Si vlan o user_vlan no son dígitos, se calcula a partir del puerto
        vlan = payload.get('vlan', payload.get('user_vlan'))
        if not vlan or not str(vlan).isdigit():
            vlan = str(100 + puerto_val)

        # 'interface gpon' y 'quit' se gestionan en execute_set_breach_sequence
        return {
            'gpon_commands': [
                f"ont port native-vlan {port_num} {ont_id} eth 1 vlan {vlan} priority {priority}",
            ],
        }

    def execute_set_breach_sequence(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta el flujo de configuración de VLAN nativa con sincronización explícita de prompts."""
        responses = []
        already_exists_detected = False
        already_exists_msg = ""
        try:
            if not self.is_connected:
                raise OLTConnectionError("No hay sesión activa. Llama connect() antes de ejecutar secuencias.")

            # Resetear prompt al estado base antes de iniciar
            self._reset_to_base_prompt()

            # 1. Modo Privilegiado  (> → #)
            resp = self.enter_privileged_mode()
            self.check_response_for_errors('enable', resp)
            responses.append(('enable', resp))

            # 2. Modo Configuración  (# → (config)#)
            resp = self.enter_config_mode()
            self.check_response_for_errors('config', resp)
            responses.append(('config', resp))

            # 3. Entrar a interfaz GPON  ((config)# → (config-if-gpon-X/X)#)
            resp = self.enter_gpon_interface(payload.get('gpon_port', '0/0/0'))
            self.check_response_for_errors('interface gpon', resp)
            responses.append(('interface gpon', resp))

            # 4. Comandos dentro de (config-if-gpon-X/X)#
            cmd_groups = self.build_set_breach_commands(payload)
            for cmd in cmd_groups['gpon_commands']:
                try:
                    resp = self.send_command(
                        cmd,
                        use_timing=True,
                        delay_factor=1.5,
                    )
                    self.check_response_for_errors(cmd, resp)
                    responses.append((cmd, resp))
                except OLTAlreadyExistsError as e:
                    logger.warning(f"Advertencia de duplicidad/existente detectada y capturada en '{cmd}': {e}")
                    already_exists_detected = True
                    already_exists_msg = str(e)
                    responses.append((cmd, f"Warning/Already Exists: {e}"))

            # 5. Salir de interfaz GPON  ((config-if-gpon-X/X)# → (config)#)
            resp = self.exit_gpon_interface()
            responses.append(('quit', resp))

            if already_exists_detected:
                return {
                    'success': True,
                    'status': 'ALREADY_EXISTS',
                    'message': f"La VLAN nativa o el puerto ya estaban configurados: {already_exists_msg}",
                    'commands': [cmd for cmd, _ in responses],
                    'responses': [resp for _, resp in responses],
                }

            return {
                'success': True,
                'status': 'SUCCESS',
                'message': 'VLAN nativa cambiada exitosamente en la OLT.',
                'commands': [cmd for cmd, _ in responses],
                'responses': [resp for _, resp in responses],
            }
        except Exception as e:
            logger.error(f"Error en execute_set_breach_sequence: {e}")
            return {
                'success': False,
                'status': 'ERROR',
                'error': str(e),
                'commands': [cmd for cmd, _ in responses],
                'responses': [resp for _, resp in responses],
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
        Parsea la salida de 'display ont autofind all' en formato de bloques multi-línea.

        Formato real de Huawei OLT:
        -------------------------------------------------------
        Number              : 1
        F/S/L               : 0/7/6
        Ont SN              : 4754E4E2B3A9187 (GPON-2B3A5187)
        Password            : 0x01123334353637383930(1234567890)
        Loid                : 1234567890
        Checkcode           : 1234567890
        VendorID            : GPON
        Ont Version         : V1.0
        Ont SoftwareVersion : V1.0.2
        Ont EquipmentID     : 1601
        Ont Customized Info :
        Ont autofind time   : 06/07/2026 10:15:08-05:00
        -------------------------------------------------------
        """
        candidates = []
        # Dividir la respuesta en bloques separados por líneas de guiones
        blocks = re.split(r'-{10,}', response)

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            # Extraer F/S/L o F/S/P (frame/slot/port/line → puerto GPON)
            fsl_match = re.search(r'F/S/[LPlp]\s*:\s*(\d+/\d+/\d+)', block, re.IGNORECASE)
            if not fsl_match:
                continue
            gpon_port = fsl_match.group(1).strip()

            # Extraer Number (identificador dentro del bloque, no el ONT ID real)
            number_match = re.search(r'\bNumber\s*:\s*(\d+)', block, re.IGNORECASE)
            number = number_match.group(1).strip() if number_match else '0'

            # Extraer SN del ONT — formato: "47504F4E2B3A5187 (GPON-2B3A5187)"
            # o directamente solo el SN
            sn_match = re.search(r'Ont SN\s*:\s*([^\s\(\)]+)(?:\s*\(([^)]+)\))?', block, re.IGNORECASE)
            sn_raw = None
            sn_readable = None
            if sn_match:
                sn_raw = sn_match.group(1).strip()           # ej: "47504F4E2B3A5187"
                sn_readable = sn_match.group(2).strip() if sn_match.group(2) else sn_raw  # ej: "GPON-2B3A5187"

            # Extraer Password
            pwd_match = re.search(r'Password\s*:\s*.+?\(([^)]+)\)', block, re.IGNORECASE)
            password = pwd_match.group(1).strip() if pwd_match else None

            # Extraer Loid (puede usarse como ID de contrato)
            loid_match = re.search(r'Loid\s*:\s*(\S+)', block, re.IGNORECASE)
            loid = loid_match.group(1).strip() if loid_match else None

            # Extraer VendorID
            vendor_match = re.search(r'VendorID\s*:\s*(\S+)', block, re.IGNORECASE)
            vendor = vendor_match.group(1).strip() if vendor_match else None

            # Extraer Equipment ID
            equip_match = re.search(r'Ont EquipmentID\s*:\s*(\S+)', block, re.IGNORECASE)
            equip_id = equip_match.group(1).strip() if equip_match else None

            # Extraer tiempo de autofind
            time_match = re.search(r'Ont autofind time\s*:\s*(.+)', block, re.IGNORECASE)
            autofind_time = time_match.group(1).strip() if time_match else None

            # Usar SN raw como "mac" para compatibilidad con el sistema de activación
            # Si hay SN readable (ej: GPON-2B3A5187), lo usamos como identificador amigable
            mac = sn_raw or sn_readable

            if not gpon_port:
                logger.debug(f"Bloque sin F/S/L válido, ignorado: {block[:80]}")
                continue

            candidates.append({
                'gpon_port': gpon_port,
                'ont_id': number,           # ID auto-asignado por autofind (no es el ONT ID final)
                'mac': mac,                 # SN hexadecimal (ej: 47504F4E2B3A5187)
                'sn': sn_readable,          # SN legible (ej: GPON-2B3A5187)
                'sn_raw': sn_raw,
                'password': password,
                'loid': loid,
                'vendor': vendor,
                'equip_id': equip_id,
                'autofind_time': autofind_time,
                'status': 'pending',
                'raw': block.strip()
            })
            logger.info(f"ONT detectada: Puerto {gpon_port} | SN: {sn_readable} | SN_raw: {sn_raw}")

        logger.info(f"parse_autofind_output: {len(candidates)} ONTs encontradas en respuesta de {len(response)} chars")
        return candidates

    def display_autofind_all(self) -> list:
        """
        Ejecuta 'display ont autofind all' para listar ONTs detectadas por la OLT.
        Requiere estar en modo (config)# para que Huawei devuelva resultados.

        IMPORTANTE: El except NO traga el error de enter_privileged_mode/enter_config_mode.
        Si no se puede entrar al modo correcto, el comando se ejecutaría desde el prompt
        equivocado (>) y Huawei devolvería vacío o error silencioso.
        """
        try:
            # Entrar a modo privilegiado — lanza excepción si falla
            self.enter_privileged_mode()
            logger.info("Modo privilegiado OK (prompt: #)")

            # Entrar a modo config — lanza excepción si falla
            self.enter_config_mode()
            logger.info("Modo config OK (prompt: (config)#)")

        except Exception as e:
            logger.error(f"No se pudo entrar a modo config para autofind. Abortando. Error: {e}")
            return []

        try:
            logger.info("Ejecutando 'display ont autofind all'...")
            # read_timeout alto porque la OLT puede tardar en responder con múltiples ONTs
            response = self.send_command(
                'display ont autofind all',
                delay_factor=3.0,
                expect_string=r'\(config\)#'
            )
            logger.info(f"Respuesta cruda autofind ({len(response)} chars):\n{response[:3000]}")
        except Exception as e:
            logger.error(f"Error ejecutando 'display ont autofind all': {e}")
            return []

        candidates = self.parse_autofind_output(response)
        logger.info(f"display_autofind_all completado: {len(candidates)} ONTs detectadas")
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

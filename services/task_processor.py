"""
OPSATEL ISP - Task Processor
============================
Procesa tareas OLT desde la cola de base de datos.
Lee tareas pendientes, las valida, las ejecuta en la OLT, verifica resultados.

Autor: Arquitecto de Software Senior
Versión: 1.0.0
"""

import logging
import json
import time
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from services.olt_interface import OLTInterface, OLTConnectionError, OLTCommandError
from services.command_sanitizer import CommandSanitizer, CommandSanitizationError
import models

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTES
# ============================================================================

# Comandos OLT por acción (plantillas que se completarán)
OLT_COMMANDS = {
    'add_ont': 'ont add {gpon_port} {ont_id} sn-auth "{mac}" omci ont-lineprofile-id {profile_id} ont-srvprofile-id {srvprofile_id} desc "{description}"',
    'remove_ont': 'ont delete {gpon_port} {ont_id}',
    'add_service': 'service-port {service_port} vlan {vlan} gpon {gpon_port} ont {ont_id} gemport {gemport} multi-service user-vlan {user_vlan} tag-transform translate',
    'del_service': 'service-port delete {service_port}',
    'set_breach': 'ont port native-vlan {gpon_port} {ont_id} eth 1 vlan {vlan} priority {priority}',
}

# Umbral de potencia mínima aceptable
MIN_POWER_THRESHOLD = -27.0

# ============================================================================
# CLASE PRINCIPAL: TaskProcessor
# ============================================================================

class TaskProcessor:
    """
    Procesa tareas OLT de forma secuencial.
    Cada tarea es ejecutada con validación, reintentos y auditoría completa.
    """
    
    def __init__(self, db: Session):
        """
        Inicializa el procesador de tareas.
        
        Args:
            db: Sesión de SQLAlchemy
        """
        self.db = db
        self.olt_connections: Dict[int, OLTInterface] = {}  # Cache de conexiones
        self.current_task = None
        self.current_task_id = None
        
        logger.info("TaskProcessor inicializado")
    
    def get_olt_connection(self, olt_id: int) -> Optional[OLTInterface]:
        """
        Obtiene o crea una conexión a una OLT específica.
        Las conexiones se cachean para reutilizarlas.
        
        Args:
            olt_id: ID de la OLT en la tabla olt_config
            
        Returns:
            OLTInterface conectado o None si falla
        """
        # Si ya tenemos conexión en cache, devolverla
        if olt_id in self.olt_connections:
            conn = self.olt_connections[olt_id]
            if conn.is_connected:
                return conn
        
        # Obtener configuración de BD
        try:
            olt_config = self.db.query(models.OLTConfig).filter(
                models.OLTConfig.id == olt_id,
                models.OLTConfig.active == True
            ).first()
            
            if not olt_config:
                logger.error(f"OLT config no encontrada: {olt_id}")
                return None
            
            # Crear interfaz
            olt = OLTInterface(
                host=olt_config.host,
                port=olt_config.port,
                username=olt_config.username,
                password=olt_config.password,
                timeout=olt_config.connection_timeout,
                max_retries=olt_config.max_retries,
                retry_backoff_base=olt_config.retry_backoff_base
            )
            
            # Conectar
            if olt.connect():
                self.olt_connections[olt_id] = olt
                logger.info(f"Conexión OLT {olt_config.nombre} (ID {olt_id}) establecida")
                return olt
            else:
                logger.error(f"Fallo conectando a OLT {olt_id}")
                return None
        
        except Exception as e:
            logger.error(f"Error obteniendo conexión OLT: {e}")
            return None
    
    def disconnect_all(self):
        """Desconecta todas las OLTs en cache"""
        for olt_id, olt in self.olt_connections.items():
            try:
                olt.disconnect()
                logger.info(f"OLT {olt_id} desconectada")
            except:
                pass
        self.olt_connections.clear()
    
    def _log_attempt(
        self,
        task_id: int,
        attempt: int,
        status_before: str,
        status_after: str,
        command_sent: str,
        raw_response: str,
        success: bool,
        error_message: Optional[str],
        duration_ms: int
    ):
        """
        Registra un intento en olt_task_logs.
        
        Args:
            task_id: ID de la tarea
            attempt: Número de intento
            status_before: Estado anterior
            status_after: Estado nuevo
            command_sent: Comando enviado (sanitizado)
            raw_response: Respuesta cruda de la OLT
            success: Si fue exitoso
            error_message: Mensaje de error (si aplica)
            duration_ms: Duración en milisegundos
        """
        try:
            log_entry = models.OLTTaskLog(
                task_id=task_id,
                attempt=attempt,
                status_before=status_before,
                status_after=status_after,
                command_sent=command_sent,
                raw_response=raw_response,
                success=success,
                error_message=error_message,
                duration_ms=duration_ms,
                log_message=f"[Attempt {attempt}] {'OK' if success else 'FAIL'}"
            )
            self.db.add(log_entry)
            self.db.commit()
            logger.debug(f"Log registrado para tarea {task_id}, intento {attempt}")
        
        except Exception as e:
            logger.error(f"Error registrando log: {e}")
    
    def _execute_command_with_retry(
        self,
        olt: OLTInterface,
        command: str,
        task_id: int,
        attempt: int,
        max_retries: int
    ) -> Tuple[bool, str, str]:
        """
        Ejecuta un comando con reintentos automáticos.
        
        Args:
            olt: Interfaz OLT
            command: Comando a ejecutar
            task_id: ID de tarea (para logging)
            attempt: Número de intento
            max_retries: Máximo de reintentos
            
        Returns:
            Tupla (éxito: bool, respuesta: str, error: str)
        """
        start_time = time.time()
        
        try:
            logger.info(f"[Tarea {task_id}] Ejecutando: {command}")
            response = olt.send_command(command, delay_factor=2.0)
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Consideramos éxito si no hay error en la respuesta
            has_error = any(err in response.lower() for err in ['error', 'fail', 'invalid', 'unknown'])
            
            if has_error:
                logger.warning(f"Respuesta con posible error: {response[:200]}")
                return False, response, f"Comando posiblemente rechazado por OLT"
            
            logger.info(f"✓ Comando ejecutado exitosamente en {duration_ms}ms")
            return True, response, ""
        
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)
            logger.error(f"✗ Error ejecutando comando (intento {attempt}/{max_retries}): {error_msg}")
            return False, "", error_msg
    
    def _build_command_from_action(self, action: str, payload: Dict[str, Any]) -> Optional[str]:
        """
        Construye comando OLT a partir de una acción y payload.
        
        Args:
            action: Tipo de acción
            payload: Payload validado y sanitizado
            
        Returns:
            Comando OLT formateado o None si error
        """
        try:
            if action not in OLT_COMMANDS:
                logger.error(f"Acción desconocida: {action}")
                return None
            
            template = OLT_COMMANDS[action]
            command = template.format(**payload)
            
            logger.debug(f"Comando generado: {command}")
            return command
        
        except KeyError as e:
            logger.error(f"Campo faltante en payload: {e}")
            return None
        except Exception as e:
            logger.error(f"Error construyendo comando: {e}")
            return None
    
    def process_task(self, task_id: int) -> bool:
        """
        Procesa una tarea específica.
        Este es el método principal de ejecución.
        
        Args:
            task_id: ID de la tarea a procesar
            
        Returns:
            True si la tarea se completó (éxito o error terminal)
            False si hubo un error crítico
        """
        self.current_task_id = task_id
        
        try:
            # Obtener tarea
            task = self.db.query(models.OLTTask).filter(
                models.OLTTask.id == task_id
            ).first()
            
            if not task:
                logger.error(f"Tarea no encontrada: {task_id}")
                return False
            
            self.current_task = task
            logger.info(f"\n{'='*60}")
            logger.info(f"PROCESANDO TAREA: {task_id}")
            logger.info(f"Acción: {task.action}, Cliente: {task.cliente_id}")
            logger.info(f"{'='*60}")
            
            # Validar payload
            try:
                validated_payload = CommandSanitizer.validate_payload(task.action, json.loads(task.payload))
            except CommandSanitizationError as e:
                logger.error(f"✗ Payload inválido: {e}")
                task.status = 'failed'
                task.error_message = f"Payload validation: {e}"
                task.error_code = 'INVALID_PAYLOAD'
                self.db.commit()
                return True  # Error terminal
            except json.JSONDecodeError as e:
                logger.error(f"✗ Payload no es JSON válido: {e}")
                task.status = 'failed'
                task.error_message = f"JSON decode error: {e}"
                task.error_code = 'INVALID_JSON'
                self.db.commit()
                return True
            
            # Obtener conexión OLT
            olt = self.get_olt_connection(task.olt_id)
            if not olt:
                logger.error(f"✗ No se pudo obtener conexión OLT {task.olt_id}")
                task.status = 'retry'
                task.error_message = f"No connection to OLT {task.olt_id}"
                task.error_code = 'OLT_UNAVAILABLE'
                self.db.commit()
                return True  # Podrá reintentar después
            
            # Marcar como processing
            task.status = 'processing'
            task.started_at = datetime.now()
            self.db.commit()
            
            # Construir y ejecutar comando
            if task.action in ['add_ont', 'remove_ont', 'set_breach']:
                if task.action == 'add_ont':
                    result = olt.execute_activation_sequence(validated_payload)
                elif task.action == 'remove_ont':
                    result = olt.execute_removal_sequence(validated_payload)
                elif task.action == 'set_breach':
                    result = olt.execute_set_breach_sequence(validated_payload)
                
                success = result.get('success', False)
                last_response = json.dumps(result, ensure_ascii=False)
                last_error = result.get('error', '')
                command = '; '.join(result.get('commands', []))
            else:
                command = self._build_command_from_action(task.action, validated_payload)
                if not command:
                    logger.error("No se pudo construir comando")
                    task.status = 'failed'
                    task.error_message = "Command building failed"
                    task.error_code = 'COMMAND_BUILD_FAIL'
                    self.db.commit()
                    return True
                
                # Ejecutar con reintentos
                success = False
                last_response = ""
                last_error = ""
                
                for attempt in range(1, 4):
                    success_attempt, response, error = self._execute_command_with_retry(
                        olt, command, task_id, attempt, 3
                    )
                    
                    last_response = response
                    last_error = error
                    task.retry_count = attempt
                    
                    # Log del intento
                    self._log_attempt(
                        task_id=task_id,
                        attempt=attempt,
                        status_before='processing',
                        status_after='completed' if success_attempt else 'retry',
                        command_sent=command,
                        raw_response=response[:1000],  # Limitar tamaño
                        success=success_attempt,
                        error_message=error,
                        duration_ms=0  # Calculado en OLTInterface
                    )
                    
                    if success_attempt:
                        success = True
                        break
                    
                    # Wait antes de reintentar
                    if attempt < 3:
                        wait_time = 2 ** (attempt - 1)  # Exponential backoff
                        logger.info(f"Esperando {wait_time}s antes de reintentar...")
                        time.sleep(wait_time)

            if task.action == 'add_ont':
                self._log_attempt(
                    task_id=task_id,
                    attempt=1,
                    status_before='processing',
                    status_after='completed' if success else 'retry',
                    command_sent=command,
                    raw_response=last_response[:1000],
                    success=success,
                    error_message=last_error,
                    duration_ms=0
                )
            
            # Actualizar tarea según resultado
            task.response = last_response
            task.error_message = last_error
            
            if success:
                logger.info(f"✓ Comando ejecutado con éxito")
                
                # Para 'add_ont' y 'add_service', verificar potencia
                if task.action in ['add_ont', 'add_service', 'check_power']:
                    logger.info("Verificando potencia del ONT...")
                    time.sleep(2)  # Esperar a que se sincronice
                    
                    gpon_port = validated_payload.get('gpon_port', '0/0/0')
                    ont_id = validated_payload.get('ont_id', '0')
                    
                    power_check = olt.check_ont_power(gpon_port, ont_id)
                    
                    if power_check.get('power') is not None:
                        power_val = power_check['power']
                        
                        if power_val >= MIN_POWER_THRESHOLD:
                            logger.info(f"✓ Potencia verificada: {power_val} dBm (OK)")
                            task.response_json = json.dumps(power_check)
                            task.status = 'completed'
                            
                            # Actualizar cliente
                            cliente = self.db.query(models.Cliente).filter(
                                models.Cliente.id == task.cliente_id
                            ).first()
                            if cliente:
                                cliente.potencia_verificada = True
                                cliente.potencia_last_check = datetime.now()
                                cliente.olt_sync_status = 'synced'
                                cliente.estado = 'Activo'
                                logger.info(f"Cliente {cliente.id} marcado como Activo")
                        else:
                            logger.warning(f"Potencia fuera de rango: {power_val} dBm (mín: {MIN_POWER_THRESHOLD})")
                            task.status = 'retry'
                            task.error_message = f"Power out of range: {power_val} dBm"
                            task.response_json = json.dumps(power_check)
                    else:
                        logger.warning("No se pudo leer potencia del ONT")
                        task.status = 'retry'
                        task.error_message = "Could not read ONT power"
                        task.response_json = json.dumps(power_check)
                else:
                    # Otra acción
                    task.status = 'completed'
            else:
                logger.error(f"✗ Comando falló después de reintentos")
                task.status = 'failed'
                task.error_code = 'COMMAND_FAILED'
            
            # Finalizar
            task.completed_at = datetime.now()
            self.db.commit()
            
            # Log final
            logger.info(f"Tarea {task_id} completada: status={task.status}")
            logger.info(f"{'='*60}\n")
            
            return True
        
        except Exception as e:
            logger.error(f"✗ Error crítico procesando tarea: {type(e).__name__}: {e}")
            if task:
                task.status = 'failed'
                task.error_message = f"Critical error: {e}"
                task.error_code = 'CRITICAL_ERROR'
                task.completed_at = datetime.now()
                self.db.commit()
            return False
    
    def process_pending_tasks(self, batch_size: int = 1) -> int:
        """
        Procesa todas las tareas pendientes.
        
        Args:
            batch_size: Cuántas tareas procesar en este ciclo (default 1 = secuencial)
            
        Returns:
            Número de tareas procesadas
        """
        try:
            # Obtener tareas pendientes (ordenadas por prioridad y fecha)
            pending_tasks = self.db.query(models.OLTTask).filter(
                models.OLTTask.status.in_(['pending', 'retry'])
            ).order_by(
                models.OLTTask.priority.desc(),
                models.OLTTask.created_at.asc()
            ).limit(batch_size).all()
            
            if not pending_tasks:
                logger.debug("No hay tareas pendientes")
                return 0
            
            logger.info(f"Encontradas {len(pending_tasks)} tareas pendientes")
            
            processed_count = 0
            for task in pending_tasks:
                try:
                    if self.process_task(task.id):
                        processed_count += 1
                except Exception as e:
                    logger.error(f"Error procesando tarea {task.id}: {e}")
            
            return processed_count
        
        except Exception as e:
            logger.error(f"Error en process_pending_tasks: {e}")
            return 0


# ============================================================================
# FUNCIONES DE TESTING
# ============================================================================

def test_task_processor():
    """Test básico del TaskProcessor"""
    print("=" * 60)
    print("TESTING: TaskProcessor")
    print("=" * 60)
    
    # Esta función requeriría acceso a BD real para testear
    print("TaskProcessor requiere BD real para testing.")
    print("Los tests se ejecutarán en integration tests.")
    
    print("=" * 60)
    print("TEST COMPLETE\n")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    test_task_processor()

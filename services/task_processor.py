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
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
# pyrefly: ignore [missing-import]
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

    El caché de conexiones SSH (self.olt_connections) persiste durante toda la vida
    del daemon — solo se crea UN login SSH por OLT y se reutiliza indefinidamente.

    La sesión de BD (self.db) es inyectada desde el daemon en cada ciclo:
        processor.db = SessionLocal()
        processor.process_pending_tasks()
        processor.db.close()
        processor.db = None
    Así la BD siempre tiene una sesión fresca sin recrear el TaskProcessor.
    """

    def __init__(self):
        """
        Inicializa el procesador. NO recibe sesión de BD en el constructor.
        La sesión se inyecta por ciclo desde el daemon.
        """
        self.db: Optional[Session] = None
        self.olt_connections: Dict[int, OLTInterface] = {}  # Caché SSH permanente
        self.failed_olts_this_run = set()  # Evita reintentar conexiones SSH fallidas en el mismo ciclo
        self.current_task = None
        self.current_task_id = None

        # Backoff persistente entre ciclos para conexiones SSH fallidas.
        # Clave: olt_id → número de fallos consecutivos
        self.olt_connection_failures: Dict[int, int] = {}
        # Clave: olt_id → timestamp (time.time()) mínimo para el próximo intento
        self.olt_next_retry_time: Dict[int, float] = {}

        logger.info("TaskProcessor inicializado (sin sesión BD todavía)")

    def pre_connect_active_olts(self, db: Session):
        """Pre-conecta a todas las OLTs activas al iniciar el worker"""
        self.db = db
        try:
            active_olts = db.query(models.OLTConfig).filter(models.OLTConfig.active == True).all()
            for config in active_olts:
                logger.info(f"Pre-conectando a OLT {config.nombre} (ID {config.id})...")
                self.get_olt_connection(config.id)
        except Exception as e:
            logger.error(f"Error en pre-conexión de OLTs: {e}")
        finally:
            self.db = None
    
    def _check_olt_alive(self, olt: OLTInterface) -> bool:
        """
        Verifica que la sesión SSH sigue activa enviando un comando inocuo.
        Netmiko puede reportar is_connected=True aunque Huawei ya cerró la sesión,
        por lo que hay que comprobarlo activamente.
        """
        try:
            if not olt.connection or not olt.is_connected:
                return False
            # Enviar un newline como keepalive silencioso y rápido
            prompt = olt.connection.send_command_timing("\n", delay_factor=0.5)
            if prompt:
                return True
            return False
        except Exception:
            return False

    def _get_backoff_seconds(self, failures: int) -> int:
        """Retorna segundos de espera según el número de fallos SSH consecutivos.
        
        Args:
            failures: Número de fallos SSH acumulados para esta OLT.
            
        Returns:
            Segundos a esperar antes del próximo intento de conexión.
        """
        if failures <= 1:
            return 30
        elif failures == 2:
            return 60
        else:
            return 120

    def get_olt_connection(self, olt_id: int) -> Optional[OLTInterface]:
        """
        Obtiene o crea una conexión a una OLT específica.
        El caché SSH persiste durante toda la vida del daemon.
        Solo reconecta si la sesión está realmente muerta.

        Respeta el backoff 30s/60s/120s entre fallos SSH consecutivos
        para evitar saturar el mecanismo anti-lockout de la OLT Huawei.
        """
        # Evitar reintentar si ya falló en esta ejecución
        if olt_id in self.failed_olts_this_run:
            logger.warning(f"Saltando intento de conexión a OLT {olt_id} porque ya falló previamente en esta ejecución")
            return None

        # Verificar throttle de backoff persistente entre ciclos
        now = time.time()
        next_retry = self.olt_next_retry_time.get(olt_id, 0)
        if now < next_retry:
            remaining = int(next_retry - now)
            failures = self.olt_connection_failures.get(olt_id, 0)
            logger.warning(
                f"OLT {olt_id} en backoff ({failures} fallos consecutivos). "
                f"Próximo intento en {remaining}s."
            )
            self.failed_olts_this_run.add(olt_id)
            return None

        # Verificar caché
        if olt_id in self.olt_connections:
            conn = self.olt_connections[olt_id]
            if conn.is_connected and self._check_olt_alive(conn):
                logger.debug(f"Reutilizando sesión SSH cacheada para OLT {olt_id}")
                return conn
            else:
                logger.warning(f"Sesión SSH para OLT {olt_id} ya no está activa. Reconectando...")
                try:
                    conn.disconnect()
                except Exception:
                    pass
                del self.olt_connections[olt_id]

        # Obtener configuración de BD
        try:
            olt_config = self.db.query(models.OLTConfig).filter(
                models.OLTConfig.id == olt_id,
                models.OLTConfig.active == True
            ).first()

            if not olt_config:
                logger.error(f"OLT config no encontrada: {olt_id}")
                self.failed_olts_this_run.add(olt_id)
                return None

            olt = OLTInterface(
                host=olt_config.host,
                port=olt_config.port,
                username=olt_config.username,
                password=olt_config.password,
                timeout=olt_config.connection_timeout,
                max_retries=olt_config.max_retries,
                retry_backoff_base=olt_config.retry_backoff_base
            )

            if olt.connect():
                # Conexión exitosa: resetear contadores de fallo para esta OLT
                self.olt_connection_failures.pop(olt_id, None)
                self.olt_next_retry_time.pop(olt_id, None)
                self.olt_connections[olt_id] = olt
                logger.info(f"Conexión SSH OLT {olt_config.nombre} (ID {olt_id}) establecida")
                return olt
            else:
                # Fallo: incrementar contador y calcular próximo intento
                failures = self.olt_connection_failures.get(olt_id, 0) + 1
                self.olt_connection_failures[olt_id] = failures
                backoff = self._get_backoff_seconds(failures)
                self.olt_next_retry_time[olt_id] = time.time() + backoff
                logger.error(
                    f"Fallo conectando a OLT {olt_id} (fallo #{failures}). "
                    f"Esperando {backoff}s antes del próximo intento."
                )
                self.failed_olts_this_run.add(olt_id)
                return None

        except OLTConnectionError as e:
            # Auth error u otro error crítico — también aplica backoff
            failures = self.olt_connection_failures.get(olt_id, 0) + 1
            self.olt_connection_failures[olt_id] = failures
            backoff = self._get_backoff_seconds(failures)
            self.olt_next_retry_time[olt_id] = time.time() + backoff
            logger.error(
                f"Error de conexión SSH OLT {olt_id}: {e}. "
                f"Fallo #{failures}, próximo intento en {backoff}s."
            )
            self.failed_olts_this_run.add(olt_id)
            return None
        except Exception as e:
            logger.error(f"Error obteniendo conexión OLT {olt_id}: {e}")
            self.failed_olts_this_run.add(olt_id)
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
            # Truncar error_message para evitar error de MySQL "Data too long for column" (VARCHAR 500)
            clean_error = str(error_message)[:450] if error_message else None
            clean_response = str(raw_response)[:1000] if raw_response else ""

            log_entry = models.OLTTaskLog(
                task_id=task_id,
                attempt=attempt,
                status_before=status_before,
                status_after=status_after,
                command_sent=command_sent,
                raw_response=clean_response,
                success=success,
                error_message=clean_error,
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
                    # -------------------------------------------------------
                    # AUTO-ESCALA: Calcular ont_id y service_port en tiempo real
                    # consultando la OLT para evitar colisiones.
                    # -------------------------------------------------------
                    try:
                        gpon_port = validated_payload.get('gpon_port', '0/0/0')

                        logger.info(
                            f"[AutoScale] Calculando ONT ID y Service Port para GPON {gpon_port}..."
                        )

                        # ── Garantizar (config)# antes de consultar la OLT ──
                        # _ensure_config_mode detecta el estado real del prompt y
                        # solo envía enable/config si son necesarios.
                        olt._ensure_config_mode()

                        # ── 1. ONT IDs en uso en la OLT (requiere estar en config) ──
                        # get_existing_ont_ids hace: interface gpon X/X →
                        # display ont info <port> all → quit (vuelve a config).
                        existing_ont_ids = olt.get_existing_ont_ids(gpon_port)

                        # ── 2. IDs reservados en la cola de tareas pendientes ──
                        pending_tasks = self.db.query(models.OLTTask).filter(
                            models.OLTTask.status.in_(['pending', 'processing', 'retry']),
                            models.OLTTask.id != task.id
                        ).all()

                        reserved_ont_ids: set = set()
                        reserved_sps: set = set()
                        for t in pending_tasks:
                            try:
                                p = json.loads(t.payload)
                                if p.get('gpon_port') == gpon_port:
                                    oid = p.get('ont_id')
                                    if oid is not None and str(oid).isdigit():
                                        reserved_ont_ids.add(int(oid))
                                sp = p.get('service_port')
                                if sp and str(sp).isdigit():
                                    reserved_sps.add(int(sp))
                            except Exception as parse_e:
                                logger.warning(
                                    f"[AutoScale] Error parseando payload tarea {t.id}: {parse_e}"
                                )

                        # ── 3. Primer ONT ID libre (0-127) ──
                        calculated_ont_id = None
                        for i in range(128):
                            if i not in existing_ont_ids and i not in reserved_ont_ids:
                                calculated_ont_id = i
                                break

                        if calculated_ont_id is None:
                            raise OLTCommandError(
                                f"No hay ONT IDs disponibles en {gpon_port} (rango 0-127 agotado)"
                            )

                        logger.info(f"[AutoScale] ONT ID seleccionado: {calculated_ont_id}")

                        # ── 4. Primer service_port libre usando rangos por puerto GPON ──
                        # Cada puerto GPON tiene un bloque fijo de 128 service-ports:
                        #   puerto P → rango [P*128 .. P*128+127]
                        # Ej: puerto 15 → [1920..2047], puerto 0 → [0..127]
                        # La OLT ES LA ÚNICA fuente de verdad — nunca usamos la BD.

                        # Extraer número de puerto del gpon_port (ej: "0/0/15" → 15)
                        gpon_parts = [p.strip() for p in str(gpon_port).split('/') if p.strip()]
                        try:
                            port_index = int(gpon_parts[2]) if len(gpon_parts) >= 3 else 0
                        except (ValueError, IndexError):
                            port_index = 0

                        sp_range_start = port_index * 128
                        sp_range_end   = sp_range_start + 127

                        logger.info(
                            f"[AutoScale-SP] Puerto GPON {port_index} → "
                            f"rango service-port [{sp_range_start}..{sp_range_end}]"
                        )

                        # Consultar la OLT directamente
                        olt_occupied_sps = set(olt.get_existing_service_ports(gpon_port))

                        # Combinar con SPs reservados en tareas pendientes
                        all_occupied_sps = olt_occupied_sps | reserved_sps

                        # Recorrer el rango y elegir el primer libre (reutiliza huecos)
                        calculated_sp = None
                        for sp_candidate in range(sp_range_start, sp_range_end + 1):
                            if sp_candidate not in all_occupied_sps:
                                calculated_sp = sp_candidate
                                break

                        if calculated_sp is None:
                            raise OLTCommandError(
                                f"No hay service-ports libres en el rango "
                                f"[{sp_range_start}..{sp_range_end}] para el puerto GPON {port_index}"
                            )

                        logger.info(f"[AutoScale-SP] Service Port seleccionado: {calculated_sp}")

                        # ── DIAGNÓSTICO: resumen completo antes del ont add ──
                        logger.info(
                            f"[AutoScale][DIAGNÓSTICO] ===========================\n"
                            f"  Puerto GPON          : {gpon_port}\n"
                            f"  ONT IDs en OLT       : {sorted(existing_ont_ids)}\n"
                            f"  ONT IDs en cola      : {sorted(reserved_ont_ids)}\n"
                            f"  ONT ID seleccionado  : {calculated_ont_id}\n"
                            f"  SPs en OLT (puerto)  : {sorted(olt_occupied_sps)}\n"
                            f"  SPs en cola          : {sorted(reserved_sps)}\n"
                            f"  SP rango             : [{sp_range_start}..{sp_range_end}]\n"
                            f"  SP seleccionado      : {calculated_sp}\n"
                            f"[AutoScale][DIAGNÓSTICO] ==========================="
                        )

                        # ── 5. Inyectar en payload y persistir ──
                        validated_payload['ont_id'] = str(calculated_ont_id)
                        validated_payload['service_port'] = str(calculated_sp)
                        task.payload = json.dumps(validated_payload)
                        self.db.commit()
                        logger.info(
                            f"[AutoScale] Tarea {task.id}: ont_id={calculated_ont_id}, "
                            f"service_port={calculated_sp}"
                        )

                    except Exception as autoscale_err:
                        logger.error(
                            f"[AutoScale] Error fatal: {autoscale_err}"
                        )
                        task.status = 'failed'
                        task.error_message = f"AutoScale failed: {autoscale_err}"
                        task.error_code = 'AUTOSCALE_FAILED'
                        self.db.commit()
                        return True

                    # execute_activation_sequence llama _ensure_config_mode internamente
                    # y detecta que ya estamos en (config)# → no reenvía enable/config.
                    result = olt.execute_activation_sequence(validated_payload)
                elif task.action == 'remove_ont':
                    result = olt.execute_removal_sequence(validated_payload)
                elif task.action == 'set_breach':
                    result = olt.execute_set_breach_sequence(validated_payload)
                elif task.action == 'clean_unused_bridges':
                    logger.info("[CleanBridges Task] Iniciando limpieza global de autofind en la OLT...")
                    result = olt.clean_unused_bridges()
                
                # Si la secuencia falló y la sesión SSH quedó rota, limpiar del caché
                # para que la próxima tarea fuerce una reconexión limpia.
                if not result.get('success') and not olt.is_connected:
                    logger.warning(f"Sesión OLT {task.olt_id} rota tras error. Eliminando del caché.")
                    self.olt_connections.pop(task.olt_id, None)
                
                success = result.get('success', False)
                result_status = result.get('status', 'SUCCESS')
                last_response = json.dumps(result, ensure_ascii=False)
                
                if result_status == 'ALREADY_EXISTS':
                    last_error = result.get('message', 'La ONT o parte de la configuración ya existía en la OLT.')
                else:
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
                result_status = 'SUCCESS'
                
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
                        raw_response=response,
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

            if task.action in ['add_ont', 'remove_ont', 'set_breach']:
                self._log_attempt(
                    task_id=task_id,
                    attempt=1,
                    status_before='processing',
                    status_after='completed' if success else 'failed',
                    command_sent=command,
                    raw_response=last_response,
                    success=success,
                    error_message=last_error,
                    duration_ms=0
                )

            # ── Actualizar tarea según resultado ─────────────────────────────
            task.response = last_response[:1000]
            task.error_message = last_error[:1000]

            if success:
                logger.info(f"✓ Comando ejecutado con éxito. Estado: {result_status}")

                # Marcar tarea como completada de inmediato para no dejar al
                # frontend en suspenso. La potencia es un dato adicional.
                task.status = 'completed'
                task.completed_at = datetime.now()
                
                if result_status == 'ALREADY_EXISTS':
                    task.error_code = 'ALREADY_EXISTS'
                else:
                    task.error_code = None

                # ── Guardar result enriquecido en response_json AHORA ────────
                # El frontend puede leer todos los datos técnicos en cuanto la
                # tarea pasa a 'completed', sin esperar al power-check.
                if task.action in ['add_ont', 'remove_ont', 'set_breach', 'clean_unused_bridges']:
                    safe_result = {
                        k: v for k, v in result.items()
                        if k not in ('commands', 'responses')
                    }
                    task.response_json = safe_result

                # ── Persistir datos de aprovisionamiento en el cliente ────────
                if task.action == 'add_ont' and task.cliente_id:
                    cliente = self.db.query(models.Cliente).filter(
                        models.Cliente.id == task.cliente_id
                    ).first()
                    if cliente:
                        try:
                            cliente.olt_sync_status = 'synced'
                        except Exception:
                            pass
                        cliente.estado = 'Activo'
                        cliente.instalation_date = datetime.now().strftime("%Y-%m-%d")

                        # puerto: número del puerto GPON (ej: "Puerto 8")
                        port_num = result.get('port_num')
                        if port_num is not None:
                            cliente.puerto = f"Puerto {port_num}"

                        # id_port: ONT ID asignado en la OLT
                        ont_id_val = result.get('ont_id')
                        if ont_id_val is not None:
                            cliente.id_port = str(ont_id_val)

                        # service_port: número de service-port OLT
                        sp_val = result.get('service_port')
                        if sp_val is not None:
                            cliente.service_port = str(sp_val)

                        # mac: SN / MAC del equipo procesado
                        mac_val = result.get('mac')
                        if mac_val is not None:
                            cliente.mac = str(mac_val)

                        # ont: comando ont add completo (para referencia en ONT.jsx)
                        cmd_ont = result.get('cmd_ont')
                        if cmd_ont:
                            cliente.ont = cmd_ont

                        # servicio: comando service-port completo
                        cmd_servicio = result.get('cmd_servicio')
                        if cmd_servicio:
                            cliente.servicio = cmd_servicio

                        # breach: comando ont port native-vlan
                        cmd_breach = result.get('cmd_breach')
                        if cmd_breach:
                            cliente.breach = cmd_breach

                        # ip: IP asignada
                        ip_val = validated_payload.get('ip') or result.get('ip')
                        if ip_val:
                            cliente.ip = str(ip_val)

                        # dispositivo: marca/modelo/ONU
                        disp_val = validated_payload.get('dispositivo') or result.get('dispositivo')
                        if disp_val:
                            cliente.dispositivo = str(disp_val)

                        # nap: Caja NAP
                        nap_val = validated_payload.get('nap') or result.get('nap')
                        if nap_val:
                            cliente.nap = str(nap_val)
                        
                        logger.info(
                            f"Cliente {cliente.id} actualizado: "
                            f"puerto=Puerto {port_num}, id_port={ont_id_val}, "
                            f"service_port={sp_val}, mac={mac_val}, ip={ip_val}, "
                            f"dispositivo={disp_val}, nap={nap_val}, estado=Activo"
                        )

                # Verificar potencia de forma NO-BLOQUEANTE (solo añade datos,
                # no reemplaza el response_json completo ya guardado).
                # PRIMERO intentamos usar la potencia ya leída inline durante la
                # activación (rx_power / tx_power en el result). Si no vino (None),
                # hacemos un check_ont_power con la sesión activa como fallback.
                if task.action in ['add_ont', 'add_service', 'check_power']:
                    try:
                        gpon_port = validated_payload.get('gpon_port', '0/0/0')
                        ont_id    = validated_payload.get('ont_id', '0')

                        # ── 1. Potencia inline (ya capturada durante la activación) ──
                        inline_rx = result.get('rx_power')
                        inline_tx = result.get('tx_power')
                        inline_st = result.get('ont_status')

                        if inline_rx is not None:
                            logger.info(f"[Power] Usando potencia inline del result: RX={inline_rx} dBm TX={inline_tx} dBm")
                            power_val  = inline_rx
                            tx_val     = inline_tx
                            status_val = inline_st
                        else:
                            # ── 2. Fallback: consulta adicional a la OLT ──────────
                            logger.info("[Power] Potencia no disponible en result, haciendo check_ont_power fallback...")
                            time.sleep(3)  # Esperar a que ONT se sincronice
                            power_check = olt.check_ont_power(gpon_port, ont_id)
                            power_val   = power_check.get('rx_power') or power_check.get('power')
                            tx_val      = power_check.get('tx_power')
                            status_val  = power_check.get('status')

                        # ── 3. Guardar en response_json ───────────────────────────
                        if isinstance(task.response_json, dict):
                            updated_json = dict(task.response_json)
                            updated_json['potencia']   = power_val      # backward-compat
                            updated_json['rx_power']   = power_val
                            updated_json['tx_power']   = tx_val
                            updated_json['estado_ont'] = status_val
                            task.response_json = updated_json
                        else:
                            task.response_json = {
                                'potencia':   power_val,
                                'rx_power':   power_val,
                                'tx_power':   tx_val,
                                'estado_ont': status_val,
                            }

                        # ── 4. Persistir potencia en el cliente ───────────────────
                        if power_val is not None:
                            logger.info(f"[Power] Potencia ONT: RX={power_val} dBm TX={tx_val} dBm Status={status_val}")
                            if task.action == 'add_ont' and task.cliente_id:
                                cliente = self.db.query(models.Cliente).filter(
                                    models.Cliente.id == task.cliente_id
                                ).first()
                                if cliente:
                                    cliente.potencia = str(power_val)
                                    try:
                                        cliente.potencia_verificada = True
                                        cliente.potencia_last_check = datetime.now()
                                    except Exception:
                                        pass  # Columnas opcionales, ignorar si no existen
                        else:
                            logger.warning("[Power] No se pudo leer potencia del ONT (no crítico, tarea ya completada)")
                    except Exception as pw_err:
                        logger.warning(f"[Power] Error en verificación de potencia (no crítico): {pw_err}")

                # ── PASO MIKROTIK: Lease DHCP → Estático ──────────────────────
                # Se ejecuta SÓLO si add_ont fue exitoso. Best-effort: nunca falla la tarea.
                if task.action == 'add_ont' and success and task.cliente_id:
                    mt_logs = []
                    def log_mt(msg):
                        logger.info(msg)
                        mt_logs.append(msg)

                    try:
                        from network.adapters.mikrotik import MikroTikAdapter, MikroTikAdapterError
                        import time as _time

                        log_mt("[MikroTik] Iniciando paso de lease DHCP → estático.")

                        # Cargar config de OLT (que contiene datos MikroTik)
                        olt_cfg = self.db.query(models.OLTConfig).filter(
                            models.OLTConfig.id == task.olt_id
                        ).first()

                        if not olt_cfg or not olt_cfg.mikrotik_host:
                            log_mt("[MikroTik] No hay MikroTik configurado en la OLT para este nodo. Omitiendo.")
                        else:
                            # Cargar cliente actualizado con los datos ya persistidos
                            mt_cliente = self.db.query(models.Cliente).filter(
                                models.Cliente.id == task.cliente_id
                            ).first()

                            # Intentar aprender la MAC del cliente directamente desde el service-port en la OLT
                            service_port_val = validated_payload.get('service_port') or (result.get('service_port') if 'result' in locals() else None)
                            real_client_mac = None
                            if service_port_val:
                                log_mt(f"[MikroTik] Intentando aprender la MAC real del cliente desde el service-port {service_port_val} en la OLT...")
                                for mac_attempt in range(1, 6): # 5 intentos x 3 segundos
                                    try:
                                        _time.sleep(3)
                                        real_client_mac = olt.get_mac_from_service_port(str(service_port_val))
                                        if real_client_mac:
                                            log_mt(f"[MikroTik] ¡MAC real aprendida desde la OLT!: {real_client_mac}")
                                            break
                                    except Exception as mac_err:
                                        log_mt(f"[MikroTik] Intento {mac_attempt} de lectura de MAC fallido: {mac_err}")
                            
                            if real_client_mac:
                                mt_mac = real_client_mac
                            else:
                                mt_mac = validated_payload.get('mac', '')
                                log_mt(f"[MikroTik] No se pudo aprender la MAC real, usando MAC de la ONT ({mt_mac}) como fallback")

                            gpon_port = validated_payload.get('gpon_port', '0/0/0')

                            # Extraer número de puerto GPON (ej: "0/0/15" -> 15)
                            gpon_parts = [p.strip() for p in str(gpon_port).split('/') if p.strip()]
                            try:
                                port_idx = int(gpon_parts[2]) if len(gpon_parts) >= 3 else 0
                            except (ValueError, IndexError):
                                port_idx = 0

                            # En tu MikroTik, el puerto 15 usa "dhcp16". Intentaremos ambas variantes: dhcp{puerto+1} y dhcp{puerto}
                            dhcp_servers_to_try = [
                                f"dhcp{port_idx + 1}",
                                f"dhcp{port_idx}",
                                f"dhcp-{port_idx + 1}",
                                f"dhcp-{port_idx}",
                            ]
                            if mt_cliente.nodo:
                                dhcp_servers_to_try.append(f"dhcp-{mt_cliente.nodo.lower()}")

                            if mt_cliente and mt_mac:
                                comment = f"{str(mt_cliente.id).zfill(6)} - {mt_cliente.nombre}"
                                log_mt(f"[MikroTik] Conectando a MikroTik {olt_cfg.mikrotik_host}:{olt_cfg.mikrotik_port or 8728}...")

                                with MikroTikAdapter(
                                    host=olt_cfg.mikrotik_host,
                                    username=olt_cfg.mikrotik_username,
                                    password=olt_cfg.mikrotik_password,
                                    port=olt_cfg.mikrotik_port or 8728
                                ) as mt:
                                    log_mt("[MikroTik] Conexión establecida. Iniciando búsqueda del lease...")
                                    lease = None
                                    clean_mac = mt_mac.replace(':', '').replace('-', '').upper()

                                    # Polling: hasta 30s (15 intentos x 2s)
                                    for poll_attempt in range(1, 16):
                                        log_mt(f"[MikroTik] Buscando lease dinámico (Intento {poll_attempt}/15)...")
                                        
                                        # Obtener leases de los servidores candidatos
                                        dynamic_leases = []
                                        for srv in dhcp_servers_to_try:
                                            try:
                                                leases_found = mt.get_dynamic_leases(server=srv)
                                                if leases_found:
                                                    dynamic_leases.extend(leases_found)
                                            except Exception:
                                                pass

                                        # Si no encontramos filtrando, intentar obtener todos los dinámicos como fallback
                                        if not dynamic_leases:
                                            try:
                                                dynamic_leases = mt.get_dynamic_leases()
                                            except Exception:
                                                dynamic_leases = []

                                        log_mt(f"[MikroTik] Total leases dinámicos encontrados en consulta: {len(dynamic_leases)}")

                                        # 1. Buscar por MAC
                                        for dl in dynamic_leases:
                                            dl_mac = dl.get('mac-address', '').replace(':', '').replace('-', '').upper()
                                            if dl_mac == clean_mac:
                                                lease = dl
                                                log_mt(f"[MikroTik] Match por MAC exitoso: {dl.get('address')}")
                                                break

                                        # 2. Buscar por Client ID
                                        if not lease:
                                            for dl in dynamic_leases:
                                                if dl.get('client-id') == str(mt_cliente.id):
                                                    lease = dl
                                                    log_mt(f"[MikroTik] Match por Client ID exitoso: {dl.get('address')}")
                                                    break

                                        # 3. Buscar por Hostname
                                        if not lease and mt_cliente.nombre:
                                            clean_host = mt_cliente.nombre.lower().strip()
                                            for dl in dynamic_leases:
                                                if dl.get('host-name', '').lower().strip() == clean_host:
                                                    lease = dl
                                                    log_mt(f"[MikroTik] Match por Hostname exitoso: {dl.get('address')}")
                                                    break

                                        # 4. Fallback crítico: Si no hay match directo pero hay EXACTAMENTE UN lease dinámico 
                                        #    activo en el servidor del puerto GPON respectivo (ej: dhcp16), asumimos que es ese cliente.
                                        if not lease and len(dynamic_leases) == 1:
                                            lease = dynamic_leases[0]
                                            log_mt(f"[MikroTik] Match por descarte: Único lease dinámico en el servidor del puerto: {lease.get('address')}")

                                        # 5. Fallback por si hay múltiples pero uno es del rango/servidor correcto y tiene estado 'bound'
                                        if not lease and dynamic_leases:
                                            routers_leases = [
                                                dl for dl in dynamic_leases 
                                                if any(term in dl.get('host-name', '').lower() for term in ['rtkgw', 'archer', 'tplink', 'merkusys', 'huawei', 'netis', 'tenda', 'dlink', 'deco'])
                                            ]
                                            if routers_leases:
                                                lease = routers_leases[0]
                                                log_mt(f"[MikroTik] Match por descarte (Router detectado): {lease.get('address')} ({lease.get('host-name')})")
                                            else:
                                                lease = dynamic_leases[0]
                                                log_mt(f"[MikroTik] Match por descarte (Primer lease dinámico disponible): {lease.get('address')}")

                                        if lease:
                                            _time.sleep(1)
                                            break

                                        _time.sleep(2)

                                    if not lease:
                                        log_mt(f"[MikroTik] [ADVERTENCIA] No se encontró lease dinámico para MAC {mt_mac} tras 30s.")
                                    else:
                                        # Soporte para .id (RouterOS estándar) y id
                                        lease_id = lease.get('.id') or lease.get('id')
                                        lease_ip = lease.get('address', '')
                                        lease_server = lease.get('server', 'unknown')
                                        
                                        log_mt(f"[MikroTik] Lease dinámico encontrado. ID: {lease_id} | IP: {lease_ip} | Server: {lease_server}")

                                        # Convertir a estático
                                        log_mt(f"[MikroTik] Convirtiendo lease {lease_id} a estático...")
                                        mt.make_lease_static(lease_id)
                                        log_mt("[MikroTik] Conversión a estático: OK")

                                        log_mt(f"[MikroTik] Modificando comentario a: '{comment}'...")
                                        mt.update_lease_comment(lease_id, comment)
                                        log_mt("[MikroTik] Comentario actualizado: OK")

                                        # ── Asignación de IP desde inventory_ip_pools ──────────────────
                                        # Regla 1: Si el cliente YA tiene IP asignada → siempre reutilizarla
                                        # Regla 2: Si no tiene → tomar primera LIBRE ordenada por INET_ATON
                                        import inventory_models
                                        # pyrefly: ignore [missing-import]
                                        from sqlalchemy import func, text

                                        target_ip = None

                                        # Buscar si el cliente ya tiene IP reservada históricamente
                                        existing_pool = self.db.query(inventory_models.InventoryIpPool).filter(
                                            inventory_models.InventoryIpPool.cliente_id == mt_cliente.id
                                        ).first()

                                        if existing_pool:
                                            target_ip = existing_pool.ip_address
                                            # Asegurarse que quede marcada como OCUPADO
                                            if existing_pool.estado != "OCUPADO":
                                                existing_pool.estado = "OCUPADO"
                                                existing_pool.updated_at = datetime.now()
                                            log_mt(f"[MikroTik] Cliente ya tiene IP histórica asignada: {target_ip} — reutilizando.")
                                        else:
                                            # Buscar primera IP libre del nodo, ordenada numéricamente
                                            nodo_val = (mt_cliente.nodo or "").strip()
                                            free_pool = self.db.query(inventory_models.InventoryIpPool).filter(
                                                inventory_models.InventoryIpPool.nodo == nodo_val,
                                                inventory_models.InventoryIpPool.estado == "LIBRE"
                                            ).order_by(
                                                func.inet_aton(inventory_models.InventoryIpPool.ip_address)
                                            ).with_for_update().first()

                                            if free_pool:
                                                target_ip = free_pool.ip_address
                                                free_pool.estado = "OCUPADO"
                                                free_pool.cliente_id = mt_cliente.id
                                                free_pool.updated_at = datetime.now()
                                                log_mt(f"[MikroTik] Primera IP libre del nodo '{nodo_val}': {target_ip} → marcada como OCUPADO.")
                                            else:
                                                # No hay IPs en inventario → mantener la del DHCP como fallback
                                                target_ip = lease_ip
                                                log_mt(f"[MikroTik] [ADVERTENCIA] Sin IPs libres en inventario para nodo '{nodo_val}'. Se mantiene IP DHCP: {target_ip}")

                                        # Persistir IP en el cliente y hacer commit transaccional
                                        mt_cliente.ip = target_ip
                                        self.db.commit()
                                        log_mt(f"[MikroTik] IP final asignada y persistida: {target_ip}")

                                        # Actualizar el lease estático con la IP definitiva
                                        if target_ip and target_ip != lease_ip:
                                            log_mt(f"[MikroTik] Actualizando IP del lease {lease_id}: {lease_ip} → {target_ip}...")
                                            mt.update_lease_ip(lease_id, target_ip)
                                            log_mt("[MikroTik] IP del lease actualizada: OK")
                                        else:
                                            log_mt(f"[MikroTik] IP coincide con DHCP ({target_ip}), no se modifica el lease.")

                                        log_mt(f"[MikroTik] ✓ Aprovisionamiento exitoso. IP final: {target_ip}.")

                                        # ── Reiniciar ONT en la OLT para que adopte la nueva IP ─────────
                                        try:
                                            import time as _time2
                                            _time2.sleep(2)  # Pequeña pausa para que el lease estático se propague
                                            reset_gpon = validated_payload.get('gpon_port', '0/0/0')
                                            reset_ont_id = str(validated_payload.get('ont_id', '0'))
                                            log_mt(f"[OLT] Reiniciando ONT {reset_gpon} id={reset_ont_id} para adoptar IP {target_ip}...")
                                            reset_ok = olt.reset_ont(reset_gpon, reset_ont_id)
                                            if reset_ok:
                                                log_mt(f"[OLT] ✓ ONT reiniciada correctamente.")
                                            else:
                                                log_mt(f"[OLT] [ADVERTENCIA] El reinicio del ONT no devolvió confirmación (no crítico).")
                                        except Exception as reset_err:
                                            log_mt(f"[OLT] [ERROR] No se pudo reiniciar el ONT: {reset_err} (no crítico)")

                        # Guardar logs de MikroTik en la respuesta json de la tarea para el frontend
                        if isinstance(task.response_json, dict):
                            updated_json = dict(task.response_json)
                            updated_json['mikrotik_log'] = "\n".join(mt_logs)
                            task.response_json = updated_json

                    except Exception as mt_err:
                        log_mt(f"[MikroTik] [ERROR FATAL] Paso MikroTik falló: {mt_err}")
                        if isinstance(task.response_json, dict):
                            updated_json = dict(task.response_json)
                            updated_json['mikrotik_log'] = "\n".join(mt_logs)
                            task.response_json = updated_json
            else:
                logger.error(f"✗ Comando falló")
                task.status = 'failed'
                task.error_code = 'COMMAND_FAILED'

            # Finalizar — commit único que cierra la transacción
            task.completed_at = datetime.now()
            self.db.commit()

            
            # Log final
            logger.info(f"Tarea {task_id} completada: status={task.status}")
            logger.info(f"{'='*60}\n")
            
            return True
        
        except Exception as e:
            logger.error(f"✗ Error crítico procesando tarea: {type(e).__name__}: {e}")
            try:
                self.db.rollback()
            except Exception as rb_err:
                logger.error(f"Error haciendo rollback en process_task: {rb_err}")
            
            try:
                # Volver a consultar la tarea en la sesión limpia para marcarla como fallida
                task = self.db.query(models.OLTTask).filter(models.OLTTask.id == task_id).first()
                if task:
                    task.status = 'failed'
                    task.error_message = f"Critical error: {e}"
                    task.error_code = 'CRITICAL_ERROR'
                    task.completed_at = datetime.now()
                    self.db.commit()
            except Exception as commit_err:
                logger.error(f"No se pudo registrar estado fallido de la tarea: {commit_err}")
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
            # Limpiar caché de fallos para esta ejecución
            self.failed_olts_this_run.clear()

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

    def run_keepalive(self):
        """
        Envía un comando ligero ('display clock') a todas las sesiones SSH en caché
        para evitar que expiren por inactividad.
        """
        if not self.olt_connections:
            return
        
        logger.debug(f"Ejecutando keepalive en {len(self.olt_connections)} conexiones OLT cacheables...")
        for olt_id, olt in list(self.olt_connections.items()):
            try:
                # Comprobar si la sesión está viva enviando newline (rápido/silencioso)
                if olt.is_connected and olt.connection and self._check_olt_alive(olt):
                    # Enviar comando ligero
                    olt.send_command("display clock", use_timing=True, delay_factor=1.0)
                    logger.debug(f"✓ Keepalive ('display clock') enviado exitosamente a OLT ID {olt_id}")
                    continue
                
                logger.warning(f"✗ Keepalive falló para OLT ID {olt_id} (sin respuesta). Reconectando...")
                self.olt_connections.pop(olt_id, None)
                try:
                    olt.disconnect()
                except Exception:
                    pass
                
                # Intentar reconectar si la base de datos está disponible
                if self.db:
                    self.get_olt_connection(olt_id)
            except Exception as e:
                logger.warning(f"✗ Error en keepalive para OLT ID {olt_id}: {e}. Intentando reconectar...")
                self.olt_connections.pop(olt_id, None)
                try:
                    olt.disconnect()
                except Exception:
                    pass
                if self.db:
                    try:
                        self.get_olt_connection(olt_id)
                    except Exception as re_err:
                        logger.error(f"No se pudo reconectar OLT {olt_id} durante keepalive: {re_err}")


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


# pyrefly: ignore [parse-error]
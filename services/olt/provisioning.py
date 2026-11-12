"""
Módulo de secuencias de aprovisionamiento de OLT Huawei:
- Activación de ONTs (execute_activation_sequence)
- Retiro de ONTs y service-ports (execute_removal_sequence)
- Limpieza de ONTs no deseadas en autofind (clean_unused_bridges)
- Configuración de VLAN nativa / Modo Bridge (execute_set_breach_sequence)
"""
import time
import logging
from typing import Dict, Any

from .exceptions import (
    OLTConnectionError,
    OLTCommandError,
    OLTAlreadyExistsError,
)

logger = logging.getLogger(__name__)


class OLTProvisioningMixin:
    """Mixin que contiene las secuencias complejas de aprovisionamiento para OLTInterface."""

    def execute_activation_sequence(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta el flujo completo de activación con sincronización explícita de prompts."""
        responses = []
        already_exists_detected = False
        already_exists_msg = ""
        try:
            if not self.is_connected:
                raise OLTConnectionError("No hay sesión activa. Llama connect() antes de ejecutar secuencias.")

            # 1. Llegar a (config)# sin importar el estado actual del prompt
            self._ensure_config_mode()

            # 3. Obtener listas de comandos separadas por contexto
            cmd_groups = self.build_activation_commands(payload)
            gpon_cmds = cmd_groups['gpon_commands']
            config_cmds = cmd_groups['config_commands']
            meta = cmd_groups['metadata']

            # 4. Entrar a interfaz GPON ((config)# → (config-if-gpon-X/X)#)
            resp = self.enter_gpon_interface(payload.get('gpon_port', '0/0/0'))
            if resp:
                self.check_response_for_errors('interface gpon', resp)
                responses.append(('interface gpon', resp))

            # 5. Comandos dentro de (config-if-gpon-X/X)#
            for cmd in gpon_cmds:
                try:
                    resp = self.send_command(
                        cmd,
                        expect_string=r'\(config-if-gpon-',
                        delay_factor=0.5,
                        read_timeout=20,
                    )
                    self.check_response_for_errors(cmd, resp)
                    responses.append((cmd, resp))
                except OLTAlreadyExistsError as e:
                    logger.warning(f"Advertencia de duplicidad detectada y capturada en '{cmd}': {e}")
                    already_exists_detected = True
                    already_exists_msg = str(e)
                    responses.append((cmd, f"Warning/Already Exists: {e}"))

            # 6. Salir de interfaz GPON ((config-if-gpon-X/X)# → (config)#)
            resp = self.exit_gpon_interface()
            if resp:
                responses.append(('quit', resp))

            # 7. Comandos desde (config)# (service-port, etc.)
            for cmd in config_cmds:
                try:
                    resp = self.send_command(
                        cmd,
                        expect_string=r'\(config\)#',
                        delay_factor=0.5,
                        read_timeout=20,
                    )
                    self.check_response_for_errors(cmd, resp)
                    responses.append((cmd, resp))
                except OLTAlreadyExistsError as e:
                    logger.warning(f"Advertencia de duplicidad detectada y capturada en '{cmd}': {e}")
                    already_exists_detected = True
                    already_exists_msg = str(e)
                    responses.append((cmd, f"Warning/Already Exists: {e}"))

            # 8. VERIFICACIÓN POST-ACTIVACIÓN: Potencia óptica (inline)
            rx_power = None
            tx_power = None
            ont_status_live = None
            optical_raw = ""
            try:
                gpon_port_val = meta.get('gpon_port', '0/0/0')
                ont_id_val = meta.get('ont_id', '0')
                port_num_val = meta.get('port_num', '0')
                self.enter_gpon_interface(gpon_port_val)
                opt_cmd = f"display ont optical-info {port_num_val} {ont_id_val}"
                for power_attempt in range(4):
                    opt_resp = self.send_command(
                        opt_cmd,
                        expect_string=r'\(config-if-gpon-',
                        delay_factor=0.3,
                        read_timeout=10,
                    )
                    optical_raw = opt_resp
                    power_data = self.parse_ont_power(opt_resp)
                    rx_power = power_data.get('rx_power')
                    tx_power = power_data.get('tx_power')
                    ont_status_live = self.parse_ont_status(opt_resp)
                    if rx_power is not None:
                        break
                    if power_attempt < 3:
                        time.sleep(2)
                self.exit_gpon_interface()
                logger.info(f"[Power-Inline] RX={rx_power} TX={tx_power} Status={ont_status_live}")
            except Exception as pw_inline_err:
                logger.warning(f"No se pudo consultar potencia inline post-activación: {pw_inline_err}")
                try:
                    self.exit_gpon_interface()
                except Exception:
                    pass

            if already_exists_detected:
                return {
                    'success': True,
                    'status': 'ALREADY_EXISTS',
                    'message': f"ONT o service-port ya existían en la OLT: {already_exists_msg}",
                    'commands': [cmd for cmd, _ in responses],
                    'responses': [resp for _, resp in responses],
                    'metadata': meta,
                    'power': {
                        'rx_power': rx_power,
                        'tx_power': tx_power,
                        'ont_status': ont_status_live,
                        'raw': optical_raw,
                    }
                }

            return {
                'success': True,
                'status': 'SUCCESS',
                'message': 'ONT activada y service-port configurado exitosamente.',
                'commands': [cmd for cmd, _ in responses],
                'responses': [resp for _, resp in responses],
                'metadata': meta,
                'power': {
                    'rx_power': rx_power,
                    'tx_power': tx_power,
                    'ont_status': ont_status_live,
                    'raw': optical_raw,
                }
            }

        except Exception as e:
            logger.error(f"Error en execute_activation_sequence: {e}")
            try:
                logger.warning("[Rollback OLT] Falló la activación. Iniciando rollback en OLT...")
                self._ensure_config_mode()
                sp = meta.get('service_port')
                ont_id = meta.get('ont_id')
                port_num = meta.get('port_num')
                gpon_port = meta.get('gpon_port')
                
                if sp and str(sp).isdigit():
                    logger.info(f"[Rollback OLT] Deshaciendo service-port {sp}...")
                    self.send_command(f"undo service-port {sp}", expect_string=r'\(config\)#', delay_factor=0.5)
                
                if gpon_port and ont_id is not None:
                    logger.info(f"[Rollback OLT] Eliminando ONT {ont_id} en GPON {gpon_port}...")
                    self.enter_gpon_interface(gpon_port)
                    self.send_command(f"ont delete {port_num} {ont_id}", expect_string=r'\(config-if-gpon-', delay_factor=0.5)
                    self.exit_gpon_interface()
                logger.info("[Rollback OLT] ✓ Rollback ejecutado correctamente en Huawei OLT.")
            except Exception as rollback_err:
                logger.error(f"[Rollback OLT] ✗ Error durante el rollback en OLT: {rollback_err}")

            return {
                'success': False,
                'status': 'ERROR',
                'error': str(e),
                'commands': [cmd for cmd, _ in responses],
                'responses': [resp for _, resp in responses],
            }

    def execute_removal_sequence(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta el flujo completo de eliminación con sincronización explícita de prompts."""
        responses = []
        already_exists_detected = False
        already_exists_msg = ""
        try:
            if not self.is_connected:
                raise OLTConnectionError("No hay sesión activa. Llama connect() antes de ejecutar secuencias.")

            self._ensure_config_mode()
            cmd_groups = self.build_removal_commands(payload)

            # 4. Ejecutar undo service-port desde (config)# ANTES de entrar a la interfaz
            for cmd in cmd_groups.get('config_commands_before', []):
                try:
                    logger.info(f"Ejecutando en (config)#: {cmd}")
                    resp = self.send_command(
                        cmd,
                        expect_string=r'\(config\)#',
                        delay_factor=0.5,
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
                    logger.warning(f"Error no crítico al ejecutar '{cmd}' (posiblemente ya eliminado): {e}")
                    responses.append((cmd, f"Warning: {e}"))

            # 5. Entrar a interfaz GPON
            resp = self.enter_gpon_interface(payload.get('gpon_port', '0/0/0'))
            if resp:
                self.check_response_for_errors('interface gpon', resp)
                responses.append(('interface gpon', resp))

            # 6. Ejecutar ont delete
            for cmd in cmd_groups.get('gpon_commands', []):
                try:
                    logger.info(f"Ejecutando en (config-if-gpon)#: {cmd}")
                    resp = self.send_command(
                        cmd,
                        expect_string=r'\(config-if-gpon-',
                        delay_factor=0.5,
                    )
                    self.check_response_for_errors(cmd, resp)
                    responses.append((cmd, resp))
                    logger.info(f"✓ {cmd} ejecutado OK")
                except OLTAlreadyExistsError as e:
                    logger.warning(f"ONT ya eliminada o no existía al ejecutar '{cmd}': {e}")
                    already_exists_detected = True
                    already_exists_msg = str(e)
                    responses.append((cmd, f"Warning/Already deleted: {e}"))
                except OLTCommandError as e:
                    logger.warning(f"Error al ejecutar '{cmd}': {e}")
                    responses.append((cmd, f"Warning: {e}"))

            # 7. Salir de la interfaz GPON
            resp = self.exit_gpon_interface()
            if resp:
                responses.append(('quit', resp))

            if already_exists_detected:
                return {
                    'success': True,
                    'status': 'ALREADY_EXISTS',
                    'message': f"ONT o service-port no existían en la OLT (posiblemente ya eliminados): {already_exists_msg}",
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

    def clean_unused_bridges(self) -> Dict[str, Any]:
        """Proceso automático de limpieza de autofind."""
        responses = []
        cleaned_count = 0

        try:
            if not self.is_connected:
                raise OLTConnectionError("No hay sesión activa.")

            self._ensure_config_mode()
            candidates = self.display_autofind_all()
            logger.info(f"[CleanBridges] ONTs detectadas en autofind: {len(candidates)}")

            if not candidates:
                return {
                    'success': True,
                    'status': 'SUCCESS',
                    'message': 'No hay ONTs en autofind. Nada que limpiar.',
                    'cleaned_count': 0,
                    'commands': [],
                    'responses': []
                }

            port_ont_counter: Dict[str, int] = {}
            port_sp_counter: Dict[str, int] = {}

            for cand in candidates:
                mac = cand.get('mac') or cand.get('sn_raw') or cand.get('sn')
                gpon_port = cand.get('gpon_port', '0/0/0')

                if not mac:
                    continue

                parts = [p.strip() for p in str(gpon_port).split('/') if p.strip()]
                port_num = parts[2] if len(parts) >= 3 else "0"

                try:
                    port_num_int = int(port_num)
                except ValueError:
                    port_num_int = 0

                is_sayausi_bridge = len(parts) >= 2 and parts[1] == "1"
                profile_id = str(400 + port_num_int) if is_sayausi_bridge else str(100 + port_num_int)
                vlan = str(400 + port_num_int) if is_sayausi_bridge else str(300 + port_num_int)

                current_ont_id = port_ont_counter.get(port_num, 10)
                ont_id = str(current_ont_id)
                port_ont_counter[port_num] = current_ont_id + 1

                base_sp = port_num_int * 128 + 100
                current_sp = port_sp_counter.get(port_num, base_sp)
                service_port = str(current_sp)
                port_sp_counter[port_num] = current_sp + 1

                logger.info(f"[CleanBridges] Procesando MAC {mac} en puerto {port_num} (ont_id={ont_id}, sp={service_port})")

                self.enter_gpon_interface(gpon_port)

                cmd_add = (
                    f'ont add {port_num} {ont_id} sn-auth "{mac}" omci '
                    f'ont-lineprofile-id {profile_id} ont-srvprofile-id {profile_id} desc "PRUEBAS CHAT"'
                )
                resp_add = self.send_command(cmd_add, expect_string=r'\(config-if-gpon-', delay_factor=0.5)
                responses.append((cmd_add, resp_add))

                cmd_vlan = f'ont port native-vlan {port_num} {ont_id} eth 1 vlan {profile_id} priority 0'
                resp_vlan = self.send_command(cmd_vlan, expect_string=r'\(config-if-gpon-', delay_factor=0.5)
                responses.append((cmd_vlan, resp_vlan))

                self.exit_gpon_interface()

                cmd_sp = (
                    f'service-port {service_port} vlan {vlan} gpon {gpon_port} ont {ont_id} '
                    f'gemport {profile_id} multi-service user-vlan {profile_id} tag-transform translate'
                )
                resp_sp = self.send_command(cmd_sp, expect_string=r'\(config\)#', delay_factor=0.5)
                responses.append((cmd_sp, resp_sp))

                cmd_undo_sp = f"undo service-port {service_port}"
                resp_undo = self.send_command(cmd_undo_sp, expect_string=r'\(config\)#', delay_factor=0.5)
                responses.append((cmd_undo_sp, resp_undo))

                self.enter_gpon_interface(gpon_port)

                cmd_del = f"ont delete {port_num} {ont_id}"
                resp_del = self.send_command(cmd_del, expect_string=r'\(config-if-gpon-', delay_factor=0.5)
                responses.append((cmd_del, resp_del))

                self.exit_gpon_interface()
                cleaned_count += 1

            return {
                'success': True,
                'status': 'SUCCESS',
                'message': f"Limpieza completada. {cleaned_count} ONTs procesadas y eliminadas de autofind.",
                'cleaned_count': cleaned_count,
                'commands': [c for c, _ in responses],
                'responses': [r for _, r in responses]
            }

        except Exception as e:
            logger.error(f"Error en clean_unused_bridges: {e}", exc_info=True)
            try:
                self.exit_gpon_interface()
            except Exception:
                pass
            return {
                'success': False,
                'status': 'ERROR',
                'error': str(e),
                'commands': [c for c, _ in responses],
                'responses': [r for _, r in responses]
            }

    def execute_set_breach_sequence(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta el flujo de configuración de VLAN nativa con sincronización explícita de prompts."""
        responses = []
        already_exists_detected = False
        already_exists_msg = ""
        try:
            if not self.is_connected:
                raise OLTConnectionError("No hay sesión activa. Llama connect() antes de ejecutar secuencias.")

            self._reset_to_base_prompt()

            resp = self.enter_privileged_mode()
            self.check_response_for_errors('enable', resp)
            responses.append(('enable', resp))

            resp = self.enter_config_mode()
            self.check_response_for_errors('config', resp)
            responses.append(('config', resp))

            resp = self.enter_gpon_interface(payload.get('gpon_port', '0/0/0'))
            self.check_response_for_errors('interface gpon', resp)
            responses.append(('interface gpon', resp))

            cmd_groups = self.build_set_breach_commands(payload)
            for cmd in cmd_groups['gpon_commands']:
                try:
                    resp = self.send_command(
                        cmd,
                        expect_string=r'\(config-if-gpon-',
                        delay_factor=0.5,
                    )
                    self.check_response_for_errors(cmd, resp)
                    responses.append((cmd, resp))
                except OLTAlreadyExistsError as e:
                    logger.warning(f"Advertencia de duplicidad/existente detectada y capturada en '{cmd}': {e}")
                    already_exists_detected = True
                    already_exists_msg = str(e)
                    responses.append((cmd, f"Warning/Already Exists: {e}"))

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

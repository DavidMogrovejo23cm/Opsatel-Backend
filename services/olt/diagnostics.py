"""
Módulo de diagnóstico y operaciones de mantenimiento en OLT Huawei:
- display_autofind_all: Escaneo de ONTs no autorizadas en toda la OLT
- check_ont_power: Consulta de potencia óptica detallada en tiempo real
- get_mac_from_service_port: Búsqueda de MAC por service-port
- get_mac_from_port_ont: Búsqueda de MAC por puerto y ont_id
- reset_ont: Reinicio remoto de ONT
"""
import re
import time
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)


class OLTDiagnosticsMixin:
    """Mixin que contiene los métodos de diagnóstico, MACs y reinicio para OLTInterface."""

    def display_autofind_all(self) -> list:
        """
        Ejecuta 'display ont autofind all' para listar ONTs detectadas por la OLT.
        Requiere estar en modo (config)# para que Huawei devuelva resultados.
        """
        try:
            self.enter_privileged_mode()
            logger.info("Modo privilegiado OK (prompt: #)")
            self.enter_config_mode()
            logger.info("Modo config OK (prompt: (config)#)")
        except Exception as e:
            logger.error(f"No se pudo entrar a modo config para autofind. Abortando. Error: {e}")
            return []

        try:
            logger.info("Ejecutando 'display ont autofind all'...")
            response = self.send_command(
                'display ont autofind all',
                delay_factor=1.0,
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
        Verifica la potencia de un ONT específico en tiempo real con reintentos y lectura completa.
        """
        try:
            parts = [p.strip() for p in str(gpon_port).split('/') if p.strip()]
            if len(parts) >= 3:
                gpon_interface = f"{parts[0]}/{parts[1]}"
                port_num = parts[2]
            else:
                gpon_interface = '/'.join(parts[:2]) if len(parts) >= 2 else '0/0'
                port_num = parts[-1] if parts else '0'

            logger.info(f"[check_ont_power] Consultando potencia ONT {gpon_port} (interfaz {gpon_interface}, puerto {port_num}, ID {ont_id})...")
            
            self._ensure_config_mode()

            self.send_command(
                f"interface gpon {gpon_interface}",
                expect_string=r'\(config-if-gpon-',
                delay_factor=0.3
            )
            self._current_mode = "gpon"
            self._current_gpon = gpon_interface

            optical_data: Dict[str, Optional[float]] = {
                'rx_power': None,
                'tx_power': None,
                'olt_rx_power': None,
                'temperature': None,
                'voltage': None,
                'bias_current': None,
            }
            status_val = None
            uptime_val = None
            last_response = ""

            # 1. Consultar display ont optical-info con reintentos para estabilización
            cmd_optical = f"display ont optical-info {port_num} {ont_id}"
            for attempt in range(1, 4):
                try:
                    resp_opt = self.send_command(
                        cmd_optical,
                        expect_string=r'\(config-if-gpon-',
                        delay_factor=0.3,
                        read_timeout=12
                    )
                    last_response = resp_opt
                    parsed_opt = self.parse_ont_optical_full(resp_opt)
                    optical_data.update({k: v for k, v in parsed_opt.items() if v is not None})

                    if optical_data.get('rx_power') is not None:
                        break

                    if attempt < 3:
                        time.sleep(1.5)
                except Exception as opt_err:
                    logger.debug(f"[check_ont_power] Intento {attempt} de optical-info falló: {opt_err}")

            # 2. Consultar display ont info para obtener Run state (online/offline) y Last up time
            cmd_info = f"display ont info {port_num} {ont_id}"
            try:
                resp_info = self.send_command(
                    cmd_info,
                    expect_string=r'\(config-if-gpon-',
                    delay_factor=0.3,
                    read_timeout=12
                )
                status_val = self.parse_ont_status(resp_info)
                m_up = re.search(r'Last\s*up\s*time\s*:\s*([^\r\n]+)', resp_info, re.IGNORECASE)
                if m_up:
                    up_str = m_up.group(1).strip()
                    if up_str != '-':
                        uptime_val = up_str
            except Exception as info_err:
                logger.debug(f"[check_ont_power] Error consultando display ont info: {info_err}")

            # 3. Salir de la interfaz GPON limpiamente
            try:
                self.send_command("quit", expect_string=r'\(config\)#', delay_factor=0.3)
                self._current_mode = "config"
                self._current_gpon = None
            except Exception:
                pass

            rx_p = optical_data.get('rx_power')
            return {
                'power': rx_p,
                'rx_power': rx_p,
                'tx_power': optical_data.get('tx_power'),
                'olt_rx_power': optical_data.get('olt_rx_power'),
                'temperature': optical_data.get('temperature'),
                'voltage': optical_data.get('voltage'),
                'bias_current': optical_data.get('bias_current'),
                'status': status_val or ('online' if rx_p is not None else 'offline'),
                'uptime': uptime_val,
                'response': last_response,
                'gpon_port': gpon_port,
                'ont_id': ont_id,
                'timestamp': datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error verificando potencia: {e}")
            try:
                self.send_command("quit", delay_factor=0.2)
                self._current_mode = "config"
                self._current_gpon = None
            except Exception:
                pass
            return {
                'power': None,
                'rx_power': None,
                'tx_power': None,
                'status': 'error',
                'response': str(e),
                'gpon_port': gpon_port,
                'ont_id': ont_id,
                'error': str(e),
                'timestamp': datetime.now().isoformat(),
            }

    def get_mac_from_service_port(self, service_port: str) -> Optional[str]:
        """
        Obtiene la dirección MAC del dispositivo conectado detrás de un service-port.
        Ejecuta: display mac-address service-port {service_port}
        """
        try:
            self._ensure_config_mode()
            command = f"display mac-address service-port {service_port}"
            logger.info(f"[OLTInterface] Obteniendo MAC del service-port {service_port}...")
            response = self.send_command(command, delay_factor=0.5)
            
            formatted_mac = self._extract_mac_from_response(response)
            if formatted_mac:
                logger.info(f"[OLTInterface] MAC encontrada para service-port {service_port}: {formatted_mac}")
                return formatted_mac
                
            logger.warning(f"[OLTInterface] No se encontró ninguna MAC registrada en el service-port {service_port}")
            return None
        except Exception as e:
            logger.error(f"[OLTInterface] Error obteniendo MAC del service-port {service_port}: {e}")
            return None

    def get_mac_from_port_ont(self, gpon_port: str, ont_id: str) -> Optional[str]:
        """
        Obtiene la dirección MAC del dispositivo conectado en un puerto GPON y ONT ID.
        Ejecuta: display mac-address port {gpon_port} ont {ont_id}
        """
        try:
            self._ensure_config_mode()
            clean_gpon = str(gpon_port).strip()
            if "/" not in clean_gpon:
                clean_gpon = f"0/0/{clean_gpon}"
            command = f"display mac-address port {clean_gpon} ont {ont_id}"
            logger.info(f"[OLTInterface] Obteniendo MAC de port {clean_gpon} ont {ont_id}...")
            response = self.send_command(command, delay_factor=0.5)
            
            formatted_mac = self._extract_mac_from_response(response)
            if formatted_mac:
                logger.info(f"[OLTInterface] MAC encontrada para port {clean_gpon} ont {ont_id}: {formatted_mac}")
                return formatted_mac
                
            logger.warning(f"[OLTInterface] No se encontró MAC para port {clean_gpon} ont {ont_id}")
            return None
        except Exception as e:
            logger.error(f"[OLTInterface] Error obteniendo MAC de port {gpon_port} ont {ont_id}: {e}")
            return None

    def reset_ont(self, gpon_port: str, ont_id: str) -> bool:
        """
        Reinicia un ONT en la OLT Huawei para que obtenga la nueva IP asignada.
        """
        try:
            parts = [p.strip() for p in str(gpon_port).split('/') if p.strip()]
            if len(parts) >= 3:
                gpon_interface = f"{parts[0]}/{parts[1]}"
                port_num = parts[2]
            else:
                gpon_interface = '/'.join(parts[:2]) if len(parts) >= 2 else '0/0'
                port_num = parts[-1] if parts else '0'

            logger.info(
                f"[OLTInterface] Reiniciando ONT: interface gpon {gpon_interface} "
                f"| ont reset {port_num} {ont_id}"
            )

            self._ensure_config_mode()

            resp = self.send_command(
                f"interface gpon {gpon_interface}",
                expect_string=r'\(config-if-gpon-', delay_factor=0.3
            )
            logger.info(f"[OLTInterface] [reset_ont] interface gpon {gpon_interface}: {resp.strip()[:120]}")

            resp = self.send_command(
                f"ont reset {port_num} {ont_id}",
                expect_string=r'(\(config-if-gpon-|y/n|are you sure|confirm)',
                delay_factor=0.5,
                read_timeout=15
            )
            logger.info(f"[OLTInterface] [reset_ont] ont reset {port_num} {ont_id}: {resp.strip()[:120]}")
            if any(q in resp.lower() for q in ['y/n', 'are you sure', 'confirm']):
                logger.info("[reset_ont] Confirmando reinicio con 'y'...")
                resp += "\n" + self.send_command('y', expect_string=r'\(config-if-gpon-', delay_factor=0.5)

            self.send_command('quit', expect_string=r'\(config\)#', delay_factor=0.3)

            logger.info(f"[OLTInterface] ✓ ONT {gpon_port} / id {ont_id} reiniciado correctamente.")
            return True

        except Exception as e:
            logger.error(f"[OLTInterface] Error al reiniciar ONT {gpon_port}/{ont_id}: {e}")
            return False

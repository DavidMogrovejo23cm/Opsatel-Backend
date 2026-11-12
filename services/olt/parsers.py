"""
Parsers de respuestas CLI de OLT Huawei:
- Potencia óptica (completa y resumida)
- Estado de ONT (Run state, control flag)
- Salida de autofind (ONTs descubiertas automáticamente)
- Extracción y normalización de direcciones MAC
"""
import re
import logging
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)


def parse_ont_optical_full(response: str) -> Dict[str, Optional[float]]:
    """
    Parsea exhaustivamente la respuesta de 'display ont optical-info' de Huawei OLT.
    Extrae rx_power (con fallback a OLT Rx si la ONT aún no reporta Rx interno),
    tx_power, olt_rx_power, temperature, voltage y bias_current.
    """
    result: Dict[str, Optional[float]] = {
        'rx_power': None,
        'tx_power': None,
        'olt_rx_power': None,
        'temperature': None,
        'voltage': None,
        'bias_current': None,
    }
    if not response:
        return result

    try:
        # 1. Potencia recibida en la ONT (Rx optical power)
        m_rx = re.search(
            r'(?<!OLT\s)(?:Rx\s*optical\s*power|RX\s*power)\s*(?:\(\s*dBm\s*\))?\s*:\s*([-+]?\d+(?:\.\d+)?)',
            response,
            re.IGNORECASE
        )
        if m_rx:
            result['rx_power'] = float(m_rx.group(1).strip())
        else:
            # Fallback: OLT Rx ONT optical power (medida directamente por el módulo SFP de la OLT)
            m_olt_rx_fallback = re.search(
                r'OLT\s+Rx\s+ONT\s+optical\s+power\s*(?:\(\s*dBm\s*\))?\s*:\s*([-+]?\d+(?:\.\d+)?)',
                response,
                re.IGNORECASE
            )
            if m_olt_rx_fallback:
                result['rx_power'] = float(m_olt_rx_fallback.group(1).strip())
            else:
                m_gen_rx = re.search(r'(?:RX|Rx)\s*power.*?:\s*([-\d.]+)', response, re.IGNORECASE)
                if m_gen_rx:
                    try:
                        result['rx_power'] = float(m_gen_rx.group(1).strip())
                    except ValueError:
                        pass

        # 2. Potencia transmitida por la ONT (Tx optical power)
        m_tx = re.search(
            r'(?:Tx\s*optical\s*power|TX\s*power|ONT\s+Tx\s+power)\s*(?:\(\s*dBm\s*\))?\s*:\s*([-+]?\d+(?:\.\d+)?)',
            response,
            re.IGNORECASE
        )
        if m_tx:
            result['tx_power'] = float(m_tx.group(1).strip())

        # 3. Potencia recibida en la OLT desde la ONT
        m_olt_rx = re.search(
            r'OLT\s+Rx\s+ONT\s+optical\s+power\s*(?:\(\s*dBm\s*\))?\s*:\s*([-+]?\d+(?:\.\d+)?)',
            response,
            re.IGNORECASE
        )
        if m_olt_rx:
            result['olt_rx_power'] = float(m_olt_rx.group(1).strip())

        # 4. Temperatura del transceptor (°C)
        m_temp = re.search(r'(?:Operating|Module|System|\b)?\s*temperature\s*(?:\(\s*C\s*\))?\s*:\s*([-+]?\d+(?:\.\d+)?)', response, re.IGNORECASE)
        if m_temp:
            result['temperature'] = float(m_temp.group(1).strip())

        # 5. Voltaje de alimentación (V)
        m_volt = re.search(r'(?:Supply\s*)?voltage\s*(?:\(\s*V\s*\))?\s*:\s*([-+]?\d+(?:\.\d+)?)', response, re.IGNORECASE)
        if m_volt:
            result['voltage'] = float(m_volt.group(1).strip())

        # 6. Corriente de polarización láser (mA)
        m_bias = re.search(r'(?:Tx\s*)?bias\s*current\s*(?:\(\s*mA\s*\))?\s*:\s*([-+]?\d+(?:\.\d+)?)', response, re.IGNORECASE)
        if m_bias:
            result['bias_current'] = float(m_bias.group(1).strip())

        return result

    except Exception as e:
        logger.error(f"Error parseando optical-info completo: {e}")
        return result


def parse_ont_power_func(response: str) -> Dict[str, Optional[float]]:
    """
    Parsea respuesta de 'display ont optical-info' para extraer potencia RX y TX.
    """
    full_data = parse_ont_optical_full(response)
    return {
        'rx_power': full_data.get('rx_power'),
        'tx_power': full_data.get('tx_power'),
    }


def parse_ont_status(response: str) -> Optional[str]:
    """
    Parsea estado de ONT de respuesta de 'display ont info' o 'display ont optical-info'.
    Detecta Run state: online / offline, Control flag: active, etc.
    """
    if not response:
        return None
    try:
        patterns = [
            r'Run\s*state\s*:\s*(\w+)',
            r'ONT\s*state\s*:\s*(\w+)',
            r'State:\s*(\w+)',
            r'(?:Current )?Status:\s*(\w+)',
            r'Control\s*flag\s*:\s*(\w+)',
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


def parse_autofind_output_func(response: str) -> list:
    """
    Parsea la salida de 'display ont autofind all' en formato de bloques multi-línea.
    """
    candidates = []
    blocks = re.split(r'-{10,}', response)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        fsl_match = re.search(r'F/S/[LPlp]\s*:\s*(\d+/\d+/\d+)', block, re.IGNORECASE)
        if not fsl_match:
            continue
        gpon_port = fsl_match.group(1).strip()

        number_match = re.search(r'\bNumber\s*:\s*(\d+)', block, re.IGNORECASE)
        number = number_match.group(1).strip() if number_match else '0'

        sn_match = re.search(r'Ont SN\s*:\s*([^\s\(\)]+)(?:\s*\(([^)]+)\))?', block, re.IGNORECASE)
        sn_raw = None
        sn_readable = None
        if sn_match:
            sn_raw = sn_match.group(1).strip()
            sn_readable = sn_match.group(2).strip() if sn_match.group(2) else sn_raw

        pwd_match = re.search(r'Password\s*:\s*.+?\(([^)]+)\)', block, re.IGNORECASE)
        password = pwd_match.group(1).strip() if pwd_match else None

        loid_match = re.search(r'Loid\s*:\s*(\S+)', block, re.IGNORECASE)
        loid = loid_match.group(1).strip() if loid_match else None

        vendor_match = re.search(r'VendorID\s*:\s*(\S+)', block, re.IGNORECASE)
        vendor = vendor_match.group(1).strip() if vendor_match else None

        equip_match = re.search(r'Ont EquipmentID\s*:\s*(\S+)', block, re.IGNORECASE)
        equip_id = equip_match.group(1).strip() if equip_match else None

        time_match = re.search(r'Ont autofind time\s*:\s*(.+)', block, re.IGNORECASE)
        autofind_time = time_match.group(1).strip() if time_match else None

        mac = sn_raw or sn_readable

        if not gpon_port:
            logger.debug(f"Bloque sin F/S/L válido, ignorado: {block[:80]}")
            continue

        candidates.append({
            'gpon_port': gpon_port,
            'ont_id': number,
            'mac': mac,
            'sn': sn_readable,
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


def extract_mac_from_response(response: str) -> Optional[str]:
    """Extrae y normaliza dirección MAC (formato XX:XX:XX:XX:XX:XX) de una salida de texto."""
    if not response:
        return None
    # 1. Standard Huawei format: xxxx-xxxx-xxxx or xxxx.xxxx.xxxx
    m = re.search(r'\b([0-9a-fA-F]{4}[-.:][0-9a-fA-F]{4}[-.:][0-9a-fA-F]{4})\b', response)
    if m:
        raw_mac = re.sub(r'[-.:]', '', m.group(1))
        return ":".join(raw_mac[i:i+2].upper() for i in range(0, 12, 2))
    # 2. Colon or hyphen separated format: xx:xx:xx:xx:xx:xx or xx-xx-xx-xx-xx-xx
    m2 = re.search(r'\b([0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2})\b', response)
    if m2:
        raw_mac = re.sub(r'[:-]', '', m2.group(1))
        return ":".join(raw_mac[i:i+2].upper() for i in range(0, 12, 2))
    return None

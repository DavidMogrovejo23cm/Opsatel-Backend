"""
Clase principal OLTInterface y herramientas de diagnóstico para OLT Huawei en OPSATEL.
Combina conexión, aprovisionamiento, diagnósticos y parsers en una interfaz unificada.
"""
import logging
from typing import Optional, Dict, Any, List

from .connection import OLTConnectionMixin
from .provisioning import OLTProvisioningMixin
from .diagnostics import OLTDiagnosticsMixin
from .command_builder import (
    build_activation_commands as _build_activation_commands,
    check_response_for_errors as _check_response_for_errors,
    build_removal_commands as _build_removal_commands,
    build_set_breach_commands as _build_set_breach_commands,
)
from .parsers import (
    parse_ont_optical_full as _parse_ont_optical_full,
    parse_ont_power_func as _parse_ont_power_func,
    parse_ont_status as _parse_ont_status,
    parse_autofind_output_func as _parse_autofind_output_func,
    extract_mac_from_response as _extract_mac_from_response,
)

logger = logging.getLogger(__name__)


class OLTInterface(OLTConnectionMixin, OLTProvisioningMixin, OLTDiagnosticsMixin):
    """
    Interfaz de conexión a OLT Huawei.
    Maneja Telnet/SSH, reintentos, buffer cleanup, aprovisionamiento y parsing.
    """

    def build_activation_commands(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Construye la secuencia de comandos Huawei para activar un ONT."""
        return _build_activation_commands(payload)

    def check_response_for_errors(self, command: str, response: str) -> None:
        """Analiza la respuesta de la OLT ante un comando específico."""
        _check_response_for_errors(command, response)

    def build_removal_commands(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Construye la secuencia de comandos Huawei para eliminar un ONT."""
        return _build_removal_commands(payload)

    def build_set_breach_commands(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Construye la secuencia de comandos Huawei para cambiar la VLAN nativa (Bridge)."""
        return _build_set_breach_commands(payload)

    @staticmethod
    def parse_ont_optical_full(response: str) -> Dict[str, Optional[float]]:
        """Parsea exhaustivamente la respuesta de 'display ont optical-info' de Huawei OLT."""
        return _parse_ont_optical_full(response)

    def parse_ont_power(self, response: str) -> Dict[str, Optional[float]]:
        """Parsea respuesta de 'display ont optical-info' para extraer potencia RX y TX."""
        return _parse_ont_power_func(response)

    @staticmethod
    def parse_ont_status(response: str) -> Optional[str]:
        """Parsea estado de ONT de respuesta de 'display ont info' o 'display ont optical-info'."""
        return _parse_ont_status(response)

    def parse_autofind_output(self, response: str) -> list:
        """Parsea la salida de 'display ont autofind all' en formato de bloques multi-línea."""
        return _parse_autofind_output_func(response)

    @staticmethod
    def _extract_mac_from_response(response: str) -> Optional[str]:
        """Extrae y normaliza dirección MAC de una respuesta de texto."""
        return _extract_mac_from_response(response)


# Export helper functions for direct module-level access
parse_ont_optical_full = OLTInterface.parse_ont_optical_full
parse_ont_status = OLTInterface.parse_ont_status


def test_olt_interface():
    """Test básico de conexión (requiere OLT real)"""
    print("=" * 60)
    print("TESTING: OLTInterface")
    print("=" * 60)
    
    OLT_HOST = "OLT_HOST_BANOS"
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
        
        if olt.connect():
            print("✓ Conectado a OLT")
            try:
                response = olt.send_command("display ont info 0/0/1 1")
                print(f"Respuesta: {response[:200]}")
            except Exception as e:
                print(f"Error ejecutando comando: {e}")
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
    print("OLTInterface módulo cargado correctamente")

"""
Fachada retrocompatible de services/olt_interface.py para OPSATEL.
Re-exporta todo el ecosistema modularizado bajo el paquete `services.olt`.
"""
from services.olt import (
    OLTConnectionError,
    OLTCommandError,
    OLTParsingError,
    OLTTimeoutError,
    OLTAlreadyExistsError,
    HUAWEI_OLT_CONFIG,
    HUAWEI_PROMPTS,
    OLTInterface,
    parse_ont_optical_full,
    parse_ont_status,
    test_olt_interface,
)

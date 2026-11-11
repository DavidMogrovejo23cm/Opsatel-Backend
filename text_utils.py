"""
@file text_utils.py
@author David Mogrovejo dmogrovejo87@gmail.com
@copyright (c) 2026 David Mogrovejo. All Rights Reserved.
@description Utilidades centrales de estandarización de texto para Opsatel.
             - Reemplaza 'ñ' y 'Ñ' por 'N'.
             - Remueve tildes y diacríticos (á, é, í, ó, ú, ü, etc.).
             - Convierte todo el texto a MAYÚSCULAS.
"""
import unicodedata
from typing import Any, Optional, List, Dict

def normalize_opsatel_text(val: Any) -> Any:
    """
    Estandariza texto en todo el sistema Opsatel:
    - Convierte 'ñ' y 'Ñ' en 'N'.
    - Elimina tildes (á->A, é->E, í->I, ó->O, ú->U, ü->U, etc.).
    - Convierte todo el texto resultante a MAYÚSCULAS.
    Si el valor no es un string o es None, lo retorna de forma segura.
    """
    if val is None:
        return None
    if not isinstance(val, str):
        val = str(val)
    if not val:
        return val

    # 1. Reemplazar explícitamente la eñe (tanto minúscula como mayúscula a N)
    s = val.replace('ñ', 'N').replace('Ñ', 'N')

    # 2. Descomponer en formato NFD para aislar diacríticos/tildes y filtrarlos
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

    # 3. Retornar en MAYÚSCULAS
    return s.upper()

def normalize_opsatel_dict(data: Dict[str, Any], keys_to_normalize: List[str]) -> Dict[str, Any]:
    """
    Normaliza una lista específica de claves dentro de un diccionario.
    """
    result = dict(data)
    for k in keys_to_normalize:
        if k in result and result[k] is not None:
            result[k] = normalize_opsatel_text(result[k])
    return result

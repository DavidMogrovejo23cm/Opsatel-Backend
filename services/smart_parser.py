import os
import re
import json
import logging
from typing import Dict, Any, List
from sam_bot_service import get_anthropic_client, CLAUDE_MODEL

logger = logging.getLogger(__name__)

def parse_unstructured_client_data(
    text: str,
    valid_nodos: List[str],
    valid_parroquias: List[str],
    valid_planes: List[str]
) -> Dict[str, Any]:
    """
    Usa Claude (Anthropic API) para analizar texto libre, estructurar
    los datos y mapearlos inteligentemente al modelo de Cliente de Opsatel.
    
    Args:
        text: El texto libre o JSON parcial ingresado por el usuario.
        valid_nodos: Lista de nombres de nodos válidos en la BD para fuzzy mapping.
        valid_parroquias: Lista de parroquias válidas en la BD.
        valid_planes: Lista de planes de internet válidos en la BD.
        
    Returns:
        Diccionario con los campos extraídos listos para mapear a Cliente.
    """
    client = get_anthropic_client()
    if not client:
        logger.error("No se pudo inicializar el cliente de Anthropic. Verifica ANTHROPIC_API_KEY.")
        raise ValueError("Servicio de Inteligencia Artificial no configurado en el backend.")

    prompt = f"""Eres el extractor de datos inteligente de OPSATEL. 
Tu tarea es analizar el texto o JSON de entrada provisto por el usuario y extraer toda la información del cliente para mapearla exactamente a las columnas de la base de datos de nuestro sistema de gestión.

Aquí están las listas de entidades válidas registradas en nuestra base de datos actual (usa estas listas para mapear inteligentemente los valores extraídos de forma insensible a mayúsculas o con variaciones tipográficas):
- NODOS VÁLIDOS: {json.dumps(valid_nodos, ensure_ascii=False)}
- PARROQUIAS VÁLIDAS: {json.dumps(valid_parroquias, ensure_ascii=False)}
- PLANES VÁLIDOS: {json.dumps(valid_planes, ensure_ascii=False)}

Entrada del usuario para analizar:
\"\"\"
{text}
\"\"\"

Campos a extraer y reglas de normalización:
1. "nombre": Nombre completo del cliente.
2. "cedula": Número de cédula, RUC, o pasaporte (solo dígitos. Si tiene 9 dígitos y empieza por 1-9, agrégale un "0" a la izquierda).
3. "cedula_tipo": Tipo de identificación. Debe ser exactamente una de estas opciones: "Cédula", "RUC", "Pasaporte". Si no se especifica, infiérelo por la longitud (10 dígitos = Cédula, 13 dígitos = RUC, otro = Pasaporte/Cédula).
4. "celular": Teléfono celular de contacto (solo dígitos, ej. "0998877665").
5. "correo": Correo electrónico.
6. "direccion": Dirección física detallada del domicilio.
7. "nodo": Mapea el nodo mencionado a uno de los NODOS VÁLIDOS. Si se parece mucho a uno de la lista, usa el valor exacto de la lista. Si no coincide con ninguno, usa el valor original o null.
8. "parroquia": Mapea la parroquia a uno de la lista de PARROQUIAS VÁLIDAS. Si se parece mucho, usa el valor exacto.
9. "plan": Mapea el plan de internet a uno de la lista de PLANES VÁLIDOS. Si el usuario menciona megas (ej: "30 megas", "plan de 50mb"), mapealo al plan correcto (ej: "Plan 30 Megas", "Plan 50 Megas", etc.).
10. "fecha_firma": Fecha del contrato o firma. Formato YYYY-MM-DD si es posible, de lo contrario el texto original.
11. "ubicacion": Coordenadas GPS (Latitud, Longitud) si están presentes, separadas por coma (ej. "-2.8974, -79.0045").
12. "tiempo": Tiempo o duración del contrato en meses (ej. "12", "24", "0").
13. "tercera_edad": Booleano (true/false) si menciona que aplica descuento de tercera edad, discapacidad, tercera edad, jubilado o ley especial.
14. "precio_plan_especial": Valor numérico decimal (float) si el plan tiene un precio de oferta o plan especial, de lo contrario null.
15. "comentarios": Notas adicionales, observaciones generales, o cualquier otro texto que no calce en los campos anteriores.
16. "mac": Dirección MAC o número de serie PON de la ONT (ej: "48575443...", "AABBCCDDEEFF"). Límpialo para dejar solo caracteres alfanuméricos y en mayúsculas.
17. "puerto": Puerto GPON / PON (ej: "Puerto 1", "Puerto 8"). Deja solo el formato "Puerto X" donde X es el número si se detecta, de lo contrario el texto extraído.
18. "ip": Dirección IP fija asignada.
19. "dispositivo": Marca y modelo del router u ONT.
20. "nap": Caja NAP (ej: "NAP 3", "Caja 12").
21. "red": Segmento de red o VLAN.
22. "clave": Clave del Wi-Fi o del equipo.
23. "tecnico": Nombre del técnico instalador.
24. "iptv_max_conn": Cantidad máxima de conexiones IPTV / pantallas (entero).
25. "iptv_activar": Booleano (true/false) si se indica que debe activarse IPTV.

Instrucciones de retorno:
Devuelve ÚNICAMENTE un objeto JSON válido con las claves mencionadas arriba. Si un campo no está en la entrada y no puede inferirse razonablemente, establécelo como null.
No incluyas explicaciones, preámbulos, ni bloques de código de markdown como ```json ... ```. Solo el texto crudo del JSON.
"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1000,
            temperature=0.0,  # Determinista
            messages=[{"role": "user", "content": prompt}]
        )
        
        raw_content = response.content[0].text.strip()
        
        # Intentar limpiar en caso de que Claude ignore la regla de no markdown
        if raw_content.startswith("```"):
            # Quitar triple acento y posible especificación de lenguaje
            raw_content = re.sub(r'^```[a-zA-Z]*\n', '', raw_content)
            raw_content = re.sub(r'\n```$', '', raw_content)
            raw_content = raw_content.strip()
            
        parsed_data = json.loads(raw_content)
        logger.info(f"Datos parseados exitosamente por Claude para el texto: {text[:50]}...")
        return parsed_data
        
    except json.JSONDecodeError as je:
        logger.error(f"Error parseando respuesta JSON de Claude: {je}. Respuesta cruda: {raw_content}")
        raise ValueError(f"La IA no retornó un formato JSON válido: {raw_content}")
    except Exception as e:
        logger.error(f"Error llamando a Anthropic en parse_unstructured_client_data: {e}")
        raise ValueError(f"Error procesando la solicitud de IA: {str(e)}")

import os
import re
import json
import requests
from typing import Optional

# Configuración de Modelos de Inteligencia Artificial
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-20241022")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT_BASE = (
    "Responde en máximo 2 frases, tono amigable y persuasivo, usa emojis y un llamado a la acción. "
    "Sé conciso, directo y evita información innecesaria."
)

PLANTILLAS = {
    "saldo": "Tu saldo es **{saldo} €**. 📈",
    "pago": "Puedes pagar aquí: {link} 💳",
    "factura": "Tu última factura: {numero_factura} - {monto} €. 📄",
}

client_gemini = None
client_anthropic = None
active_groq_model = None


def get_gemini_client():
    """Inicializa y retorna el cliente de Google Gemini si GEMINI_API_KEY o GOOGLE_API_KEY está presente"""
    global client_gemini
    if client_gemini is None:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key and api_key.strip():
            try:
                from google import genai
                client_gemini = genai.Client(api_key=api_key.strip())
                print(f"[SAM Chatbot] [IA] Cliente Google Gemini conectado exitosamente ({GEMINI_MODEL}).")
            except Exception as e:
                print(f"[SAM Chatbot] Error inicializando Google Gemini: {e}")
                client_gemini = None
        else:
            return None
    return client_gemini


def get_anthropic_client():
    """Inicializa y retorna el cliente de Anthropic Claude como alternativa"""
    global client_anthropic
    if client_anthropic is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if api_key and api_key.strip():
            try:
                import anthropic
                client_anthropic = anthropic.Anthropic(api_key=api_key.strip())
                print(f"[SAM Chatbot] [IA] Cliente Anthropic Claude conectado exitosamente ({CLAUDE_MODEL}).")
            except Exception as e:
                print(f"[SAM Chatbot] Error inicializando Anthropic: {e}")
                client_anthropic = None
        else:
            return None
    return client_anthropic


def limpiar_respuesta_ia(texto: str) -> str:
    """
    Sanea la respuesta generada por cualquier IA para WhatsApp:
    1. Remueve prefijos artificiales como 'assistant:', 'SAM:', 'Bot:', 'Respuesta:'
    2. Si el modelo alucinó un guión simulado ('\nuser:', '\ncliente:', '\nusuario:'),
       corta inmediatamente todo el texto a partir de esa línea.
    3. Elimina espacios en blanco y saltos innecesarios.
    """
    if not texto:
        return ""
    res = str(texto).strip()

    res = re.sub(r'^(?:assistant|sam|asistente|bot|respuesta)\s*:\s*', '', res, flags=re.IGNORECASE).strip()

    patron_corte = re.compile(r'\n\s*(?:user|usuario|cliente|humano|assistant|asistente)\s*:\s*', re.IGNORECASE)
    corte = patron_corte.search(res)
    if corte:
        res = res[:corte.start()].strip()

    res = re.sub(r'^(?:assistant|sam|asistente|bot|respuesta)\s*:\s*', '', res, flags=re.IGNORECASE).strip()
    return res


def llamar_groq_api(prompt: str, max_tokens: int = 500, temperature: float = 0.5, system_prompt: str = "") -> str:
    """Llama a la API de Groq consultando dinámicamente los modelos activos disponibles"""
    global active_groq_model
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key or not groq_key.strip():
        return ""
    headers = {
        "Authorization": f"Bearer {groq_key.strip()}",
        "Content-Type": "application/json"
    }

    candidate_models = []
    if active_groq_model:
        candidate_models.append(active_groq_model)
    if os.getenv("GROQ_MODEL"):
        candidate_models.append(os.getenv("GROQ_MODEL"))

    try:
        models_resp = requests.get("https://api.groq.com/openai/v1/models", headers=headers, timeout=10)
        if models_resp.status_code == 200:
            data = models_resp.json().get("data", [])
            live_ids = [m.get("id") for m in data if m.get("id")]
            chat_models = [
                m for m in live_ids
                if not any(x in m.lower() for x in ["whisper", "guard", "safeguard", "embed", "tts", "audio", "vision-preview"])
            ]
            for m in chat_models:
                if m not in candidate_models:
                    candidate_models.append(m)
    except Exception as e_mod:
        print(f"[SAM Chatbot] [Groq] Advertencia consultando modelos activos: {e_mod}")

    for fb in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen-2.5-32b", "mixtral-8x7b-32768"]:
        if fb not in candidate_models:
            candidate_models.append(fb)

    chat_url = "https://api.groq.com/openai/v1/chat/completions"
    last_err = None

    messages_payload = []
    if system_prompt and system_prompt.strip():
        messages_payload.append({"role": "system", "content": system_prompt.strip()})
    messages_payload.append({"role": "user", "content": prompt})

    for model in candidate_models:
        payload = {
            "model": model,
            "messages": messages_payload,
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        try:
            resp = requests.post(chat_url, headers=headers, json=payload, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                active_groq_model = model
                print(f"[SAM Chatbot] [Groq] [OK] Respuesta generada exitosamente con modelo: {model}")
                return data["choices"][0]["message"]["content"].strip()
            else:
                last_err = f"HTTP {resp.status_code}: {resp.text}"
                continue
        except Exception as e_req:
            last_err = str(e_req)
            continue

    if last_err:
        print(f"[SAM Chatbot] Error final en llamada a Groq: {last_err}")
    return ""


def llamar_openai_api(prompt: str, max_tokens: int = 500, temperature: float = 0.5, system_prompt: str = "") -> str:
    """Llama a la API de OpenAI (GPT-4o mini)"""
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key or not openai_key.strip():
        return ""
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {openai_key.strip()}",
        "Content-Type": "application/json"
    }
    messages_payload = []
    if system_prompt and system_prompt.strip():
        messages_payload.append({"role": "system", "content": system_prompt.strip()})
    messages_payload.append({"role": "user", "content": prompt})

    payload = {
        "model": OPENAI_MODEL,
        "messages": messages_payload,
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=25)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def hay_proveedor_ia() -> bool:
    """Verifica si hay al menos un proveedor de IA disponible"""
    return bool(
        get_gemini_client() or
        os.getenv("GROQ_API_KEY") or
        os.getenv("OPENAI_API_KEY") or
        get_anthropic_client()
    )


def generar_respuesta_ia(prompt: str, max_tokens: int = 500, temperature: float = 0.5, system_prompt: str = SYSTEM_PROMPT_BASE) -> str:
    """Genera texto usando los proveedores disponibles en orden de prioridad:
    1. Groq (Ultra-rápido, gratuito, ideal para VPS)
    2. Google Gemini
    3. OpenAI
    4. Anthropic Claude
    """
    global GEMINI_MODEL

    if os.getenv("GROQ_API_KEY"):
        try:
            res = llamar_groq_api(prompt, max_tokens, temperature, system_prompt=system_prompt)
            if res:
                return limpiar_respuesta_ia(res)
        except Exception as e_groq:
            print(f"[SAM Chatbot] Error en llamada a Groq: {e_groq}")

    client_g = get_gemini_client()
    if client_g:
        from google.genai import types
        cfg_kwargs = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if system_prompt and system_prompt.strip():
            cfg_kwargs["system_instruction"] = system_prompt.strip()
        config = types.GenerateContentConfig(**cfg_kwargs)

        model_candidates = [
            GEMINI_MODEL,
            "gemini-2.5-flash",
            "gemini-1.5-flash",
            "gemini-3.6-flash",
            "gemini-2.0-flash-exp",
            "gemini-1.5-pro",
        ]
        seen = set()
        model_list = [m for m in model_candidates if not (m in seen or seen.add(m))]

        for model_name in model_list:
            try:
                response = client_g.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config
                )
                if response and response.text:
                    if GEMINI_MODEL != model_name:
                        print(f"[SAM Chatbot] [IA] Modelo Gemini activo verificado: {model_name}")
                        GEMINI_MODEL = model_name
                    return limpiar_respuesta_ia(response.text.strip())
            except Exception as e_gem:
                err_str = str(e_gem)
                if "404" in err_str or "NOT_FOUND" in err_str or "no longer available" in err_str:
                    continue
                else:
                    print(f"[SAM Chatbot] Error en llamada a Gemini ({model_name}): {e_gem}")
                    break

    if os.getenv("OPENAI_API_KEY"):
        try:
            res = llamar_openai_api(prompt, max_tokens, temperature, system_prompt=system_prompt)
            if res:
                return limpiar_respuesta_ia(res)
        except Exception as e_oai:
            print(f"[SAM Chatbot] Error en llamada a OpenAI: {e_oai}")

    client_a = get_anthropic_client()
    if client_a:
        try:
            call_kwargs = {
                "model": CLAUDE_MODEL,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}]
            }
            if system_prompt and system_prompt.strip():
                call_kwargs["system"] = system_prompt.strip()
            response = client_a.messages.create(**call_kwargs)
            if response and response.content:
                return limpiar_respuesta_ia(response.content[0].text.strip())
        except Exception as e_ant:
            print(f"[SAM Chatbot] Error en llamada a Anthropic: {e_ant}")

    raise RuntimeError("No se pudo obtener respuesta de ningún proveedor de IA configurado.")

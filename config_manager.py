import json
import os

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "ultimo_cierre": "",
    "ultima_facturacion": "",
    "dia_corte": 20,
    "hora_corte": "01:00",
    "auto_suspension_enabled": True,
    "clientes_exentos_corte": []
}

def get_config():
    if not os.path.exists(CONFIG_FILE):
        return DEFAULT_CONFIG.copy()
    with open(CONFIG_FILE, "r") as f:
        try:
            data = json.load(f)
            merged = DEFAULT_CONFIG.copy()
            merged.update(data)
            return merged
        except:
            return DEFAULT_CONFIG.copy()

def save_config(data):
    config = get_config()
    config.update(data)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

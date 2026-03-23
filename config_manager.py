import json
import os

CONFIG_FILE = "config.json"

def get_config():
    if not os.path.exists(CONFIG_FILE):
        return {"ultimo_cierre": "", "ultima_facturacion": ""}
    with open(CONFIG_FILE, "r") as f:
        try:
            return json.load(f)
        except:
            return {"ultimo_cierre": "", "ultima_facturacion": ""}

def save_config(data):
    config = get_config()
    config.update(data)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

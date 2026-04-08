import os
import requests

API_BASE_URL = 'https://opsatel-backend-production.up.railway.app' # Try production first
# Actually, I'll try local if it's running
LOCAL_URL = 'http://localhost:8000'

test_payload = {
    "nombre": "Test Parroquia Antigravity",
    "cedula": "0000000000",
    "celular": "0999999999",
    "direccion": "Test Direccion",
    "nodo": "Test Nodo",
    "parroquia": "SAYAUSI",
    "plan": "Test Plan",
    "fecha_firma": "2026-04-08"
}

try:
    print(f"Testing LOCAL: {LOCAL_URL}")
    r = requests.post(f"{LOCAL_URL}/clientes/", json=test_payload)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text}")
except Exception as e:
    print(f"Local test failed: {e}")

try:
    print(f"Testing PROD: {API_BASE_URL}")
    r = requests.post(f"{API_BASE_URL}/clientes/", json=test_payload)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text}")
except Exception as e:
    print(f"Prod test failed: {e}")

import sys
import os
from dotenv import load_dotenv

# Cargar configuración
load_dotenv()

import whatsapp_service

def main():
    print("=== SCRIPT DE VERIFICACIÓN DE WHATSAPP ===")
    print(f"Proveedor configurado (WHATSAPP_PROVIDER): {whatsapp_service.WHATSAPP_PROVIDER}")
    print(f"URL de Puente local (WHATSAPP_BRIDGE_URL): {whatsapp_service.WHATSAPP_BRIDGE_URL}")
    print(f"Instancia de WhatsApp (WHATSAPP_INSTANCE_ID): {whatsapp_service.WHATSAPP_INSTANCE_ID}")
    print("==========================================\n")

    # Verificar estado del puente si aplica
    if whatsapp_service.WHATSAPP_PROVIDER == "local-bridge":
        print("Consultando estado del puente local...")
        status = whatsapp_service.get_whatsapp_bridge_status()
        print(f"Respuesta de estado: {status}")
        if not status.get("connected"):
            print("\n[!] ADVERTENCIA: El puente local de WhatsApp NO está conectado.")
            print("Si el estado es QR_READY, solicita el QR usando el endpoint o revisando la terminal del puente.")
            print("Si el estado es OFFLINE, asegúrate de iniciar el puente ejecutando: node whatsapp_bridge.js")
            print("Procediendo de todas formas...")
        else:
            print("\n[+] El puente local está conectado y listo.")

    print("\n--- PRUEBA DE ENVÍO INDIVIDUAL ---")
    numero = input("Ingresa un número de celular de prueba (con prefijo del país, ej: +593999999999): ").strip()
    if not numero:
        print("Operación cancelada. Número vacío.")
        sys.exit(0)

    mensaje = input("Ingresa el mensaje que deseas enviar: ").strip()
    if not mensaje:
        mensaje = "Mensaje de prueba de integración de Opsatel"

    print(f"\nIntentando enviar mensaje a: {numero}...")
    success = whatsapp_service.send_whatsapp_message(numero, mensaje)
    
    if success:
        print("\n[SUCCESS] ¡El mensaje fue despachado exitosamente!")
    else:
        print("\n[ERROR] No se pudo despachar el mensaje. Revisa los logs y configuraciones.")

if __name__ == "__main__":
    main()

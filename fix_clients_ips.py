from database import SessionLocal
import models
from sqlalchemy import func

def fix_clients_nodos_and_ips():
    db = SessionLocal()
    # 1. Obtenemos los nodos para conocer sus IPs base
    nodos = db.query(models.Nodo).all()
    # Mapeo de nombre de nodo a su IP base (usamos normalizado para matching)
    mapa_nodos = {n.nombre.upper(): n.base_ip for n in nodos}
    print(f"Map de Nodos: {mapa_nodos}")
    
    # 2. Obtenemos todos los clientes
    clientes = db.query(models.Cliente).all()
    print(f"Número total de clientes: {len(clientes)}")
    
    actualizados = 0
    fueron_modificados = 0
    
    for c in clientes:
        if not c.nodo:
            # Si no tiene nodo, ¿podemos adivinarlo por su IP?
            # Si su IP empieza por 172.18 -> SAYAUSI
            # Si su IP empieza por 172.16 -> BAÑOS
            if c.ip:
                if c.ip.startswith("172.18"):
                    c.nodo = "SAYAUSI"
                    fueron_modificados += 1
                elif c.ip.startswith("172.16"):
                    c.nodo = "BAÑOS"
                    fueron_modificados += 1
            else:
                # Si no tiene nada, por defecto a SAYAUSI? 
                # (Mejor no adivinar si no hay pistas, pero el usuario dijo 'designales un nodo a todos')
                # Voy a poner SAYAUSI como default si no hay IP
                c.nodo = "SAYAUSI"
                fueron_modificados += 1
        
        # 3. Corregir IP si el nodo es diferente
        # Normalizamos el nombre del nodo del cliente
        current_nodo_name = c.nodo.upper() if c.nodo else ""
        if current_nodo_name in mapa_nodos:
            target_base_ip = mapa_nodos[current_nodo_name]
            if c.ip and not c.ip.startswith(target_base_ip):
                # Ejemplo: Tiene 172.16.2.3 en SAYAUSI (que debería ser 172.18)
                # Reemplazamos el prefijo
                partes_ip = c.ip.split('.')
                if len(partes_ip) == 4:
                    new_ip = f"{target_base_ip}.{partes_ip[2]}.{partes_ip[3]}"
                elif len(partes_ip) == 2:
                    new_ip = f"{target_base_ip}.{partes_ip[0]}.{partes_ip[1]}"
                else:
                    new_ip = c.ip # No cambiamos si no tiene sentido
                
                if new_ip != c.ip:
                    print(f"Corrigiendo IP del cliente {c.id}: {c.ip} -> {new_ip} (Nodo: {c.nodo})")
                    c.ip = new_ip
                    fueron_modificados += 1
        
        actualizados += 1

    db.commit()
    print(f"Se revisaron {actualizados} clientes. Se realizaron {fueron_modificados} cambios en Nodo/IP.")
    db.close()

if __name__ == "__main__":
    fix_clients_nodos_and_ips()

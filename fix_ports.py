from database import SessionLocal
import models

def fix_ports():
    db = SessionLocal()
    # Let's find orphaned ports (nodo_id is None)
    orphans = db.query(models.Puerto).filter(models.Puerto.nodo_id == None).all()
    print(f"Encontrados {len(orphans)} puertos sin asignar a un Nodo.")
    
    # We have Node 1 (SAYAUSI) and Node 2 (BAÑOS)
    # IDs 1-11 seem to be SAYAUSI, IDs 12-26 seem to be BAÑOS.
    # Why? IDs 1-11 are Puerto 1-11. IDs 12-26 are Puerto 1-15.
    
    # Let's verify by checking which node uses which name more.
    for p in orphans:
        clients = db.query(models.Cliente).filter(models.Cliente.puerto == p.nombre).all()
        if clients:
            nodos_used = {}
            for c in clients:
                if c.nodo not in nodos_used:
                    nodos_used[c.nodo] = 0
                nodos_used[c.nodo] += 1
            print(f"Puerto ID {p.id} ('{p.nombre}') usado por: {nodos_used}")
            # If ID is 1-11, assign it to SAYAUSI (Node 1)?
            # If ID is 12-26, assign it to BAÑOS (Node 2)?
            if p.id <= 11:
                p.nodo_id = 1 # SAYAUSI
            elif p.id <= 26:
                p.nodo_id = 2 # BAÑOS
    
    db.commit()
    print("Corrección de puertos (ids 1-26) aplicada.")
    db.close()

if __name__ == "__main__":
    fix_ports()

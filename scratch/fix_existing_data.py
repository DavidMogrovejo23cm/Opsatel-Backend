import sys
import os

# Add parent directory to path so we can import models and database
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
import models

def clean_int_string_value(val):
    if val is None:
        return None
    s_val = str(val).strip()
    if s_val.endswith('.0'):
        try:
            f_val = float(s_val)
            if f_val.is_integer():
                return str(int(f_val))
        except:
            pass
    return s_val

def fix_existing_data():
    db = SessionLocal()
    try:
        clients = db.query(models.Cliente).all()
        print(f"Total de clientes a revisar: {len(clients)}")
        
        fixed_count = 0
        for c in clients:
            changed = False
            
            # Fields to strip .0
            fields_to_clean = ["puerto", "id_port", "service_port", "tiempo", "cod", "nap"]
            for field in fields_to_clean:
                old_val = getattr(c, field)
                if old_val is not None:
                    new_val = clean_int_string_value(old_val)
                    if new_val != old_val:
                        setattr(c, field, new_val)
                        print(f"Cliente {c.id} ({c.nombre}) - {field}: '{old_val}' -> '{new_val}'")
                        changed = True
            
            # Special logic for cedula (pad leading zero if 9 digits)
            if c.cedula is not None:
                old_ced = getattr(c, "cedula")
                clean_ced = clean_int_string_value(old_ced)
                if clean_ced and clean_ced.isdigit() and len(clean_ced) == 9:
                    clean_ced = "0" + clean_ced
                if clean_ced != old_ced:
                    c.cedula = clean_ced
                    print(f"Cliente {c.id} ({c.nombre}) - cedula: '{old_ced}' -> '{clean_ced}'")
                    changed = True
            
            # Special logic for celular (pad leading zero if 9 digits starting with 9)
            if c.celular is not None:
                old_cel = getattr(c, "celular")
                clean_cel = clean_int_string_value(old_cel)
                if clean_cel and clean_cel.isdigit() and len(clean_cel) == 9 and clean_cel.startswith("9"):
                    clean_cel = "0" + clean_cel
                if clean_cel != old_cel:
                    c.celular = clean_cel
                    print(f"Cliente {c.id} ({c.nombre}) - celular: '{old_cel}' -> '{clean_cel}'")
                    changed = True
                    
            if changed:
                fixed_count += 1
                
        if fixed_count > 0:
            db.commit()
            print(f"Se corrigieron {fixed_count} clientes con éxito en la base de datos.")
        else:
            print("No se encontraron inconsistencias (.0 o ceros faltantes) en los clientes existentes.")
            
    except Exception as e:
        db.rollback()
        print(f"Error durante la corrección: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    fix_existing_data()

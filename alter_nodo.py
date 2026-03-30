from database import engine
from sqlalchemy import text

def alter_table():
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE nodos ADD COLUMN base_ip VARCHAR(50) DEFAULT '172.16'"))
            conn.commit()
            print("Columna base_ip añadida con éxito a nodos.")
    except Exception as e:
        print(f"La columna probablemente ya existe u ocurrio otro error: {e}")

if __name__ == "__main__":
    alter_table()

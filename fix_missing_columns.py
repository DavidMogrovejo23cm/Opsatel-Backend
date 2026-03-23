from database import engine
from sqlalchemy import text

def add_columns():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE `hoja_de_c__lculo_sin_t__tulo` ADD COLUMN `ADICIONAL` VARCHAR(255)"))
            print("Columna ADICIONAL añadida")
        except Exception as e:
            print(f"ADICIONAL: {e}")
            
        try:
            conn.execute(text("ALTER TABLE `hoja_de_c__lculo_sin_t__tulo` ADD COLUMN `COMENTARIOS` VARCHAR(500)"))
            print("Columna COMENTARIOS añadida")
        except Exception as e:
            print(f"COMENTARIOS: {e}")
            
        conn.commit()

if __name__ == "__main__":
    add_columns()

from database import engine, Base

import models



def init():

    print("Iniciando la creación de tablas en la base de datos...")

    try:

        Base.metadata.create_all(bind=engine)

        print("¡Tablas creadas exitosamente!")

    except Exception as e:

        print(f"Error al conectar con la base de datos: {e}")

        print("\nASEGÚRATE DE:")

        print("1. Tener XAMPP abierto y MySQL corriendo.")

        print("2. Haber creado la base de datos llamada 'opsatel' en phpMyAdmin.")

        print("3. Que el usuario 'root' no tenga contraseña (configuración por defecto de XAMPP).")



if __name__ == "__main__":

    init()


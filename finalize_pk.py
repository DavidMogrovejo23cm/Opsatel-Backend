from sqlalchemy import create_engine, text



SQLALCHEMY_DATABASE_URL = "mysql+pymysql://root:@localhost/opsatel"

engine = create_engine(SQLALCHEMY_DATABASE_URL)



def finalize():

    print("Finalizando configuración de PK...")

    try:

        with engine.connect() as connection:

                                                             

            print("Limpiando datos no válidos en NUMERO...")

            connection.execute(text("DELETE FROM `hoja_de_c__lculo_sin_t__tulo` WHERE `NUMERO` IS NULL OR `NUMERO` = ''"))

            

                                                    

            print("Convirtiendo columna NUMERO a entero...")

                                                                                       

            connection.execute(text("ALTER TABLE `hoja_de_c__lculo_sin_t__tulo` MODIFY COLUMN `NUMERO` INT NOT NULL"))

            

                                                                                 

            print("Añadiendo Llave Primaria...")

            try:

                connection.execute(text("ALTER TABLE `hoja_de_c__lculo_sin_t__tulo` ADD PRIMARY KEY (`NUMERO`)"))

            except Exception as pk_err:

                print(f"La PK ya existía o hubo un error: {pk_err}")

            

                                         

            print("Configurando Auto Increment...")

            connection.execute(text("ALTER TABLE `hoja_de_c__lculo_sin_t__tulo` MODIFY COLUMN `NUMERO` INT AUTO_INCREMENT"))

            

            connection.commit()

            print("¡Configuración finalizada con éxito!")

            

    except Exception as e:

        print(f"Error: {e}")



if __name__ == "__main__":

    finalize()


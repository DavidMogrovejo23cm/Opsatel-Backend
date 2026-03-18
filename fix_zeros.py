from sqlalchemy import create_engine, text



SQLALCHEMY_DATABASE_URL = "mysql+pymysql://root:@localhost/opsatel"

engine = create_engine(SQLALCHEMY_DATABASE_URL)



def fix_zeros():

    print("Corrigiendo IDs para evitar conflictos con 0...")

    try:

        with engine.connect() as connection:

                                                                           

            connection.execute(text("DELETE FROM `hoja_de_c__lculo_sin_t__tulo` WHERE `NUMERO` IS NULL OR `NUMERO` = ''"))

            

                                                                                        

                                         

            print("Desplazando IDs (0 -> 1, 1 -> 2, etc.) en orden descendente...")

            connection.execute(text("UPDATE `hoja_de_c__lculo_sin_t__tulo` SET `NUMERO` = `NUMERO` + 1 ORDER BY `NUMERO` DESC"))

            

                                       

            print("Aplicando AUTO_INCREMENT...")

            connection.execute(text("ALTER TABLE `hoja_de_c__lculo_sin_t__tulo` MODIFY COLUMN `NUMERO` INT AUTO_INCREMENT;"))

            

                                                                                  

            result = connection.execute(text("SELECT MAX(`NUMERO`) FROM `hoja_de_c__lculo_sin_t__tulo`"))

            max_id = result.fetchone()[0] or 0

            print(f"ID Máximo encontrado: {max_id}, ajustando AUTO_INCREMENT a {max_id + 1}")

            connection.execute(text(f"ALTER TABLE `hoja_de_c__lculo_sin_t__tulo` AUTO_INCREMENT = {max_id + 1}"))

            

            connection.commit()

            print("¡Configuración finalizada con éxito!")

            

    except Exception as e:

        print(f"Error: {e}")



if __name__ == "__main__":

    fix_zeros()


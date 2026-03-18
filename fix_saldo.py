from sqlalchemy import create_engine, text



SQLALCHEMY_DATABASE_URL = "mysql+pymysql://root:@localhost/opsatel"

engine = create_engine(SQLALCHEMY_DATABASE_URL)



def fix_saldo_and_test():

    try:

        with engine.connect() as connection:

            print("Limpiando y convirtiendo SALDO a DECIMAL...")

                                                                     

            connection.execute(text("UPDATE `hoja_de_c__lculo_sin_t__tulo` SET `SALDO` = 0 WHERE `SALDO` IS NULL OR `SALDO` = '' OR `SALDO` NOT REGEXP '^[0-9]+(\.[0-9]+)?$'"))

            

                                                  

            connection.execute(text("ALTER TABLE `hoja_de_c__lculo_sin_t__tulo` MODIFY COLUMN `SALDO` DECIMAL(10, 2) DEFAULT 0.00"))

            

            connection.commit()

            print("Columna SALDO normalizada.")

            

                                            

            result = connection.execute(text("SELECT COUNT(*) FROM `hoja_de_c__lculo_sin_t__tulo` WHERE `ESTADO` = 'Activo'"))

            count = result.fetchone()[0]

            print(f"Clientes activos encontrados: {count}")

            

    except Exception as e:

        print(f"Error: {e}")



if __name__ == "__main__":

    fix_saldo_and_test()


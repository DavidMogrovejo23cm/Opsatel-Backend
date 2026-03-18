from sqlalchemy import create_engine, text



                                                               

SQLALCHEMY_DATABASE_URL = "mysql+pymysql://root:@localhost/opsatel"



engine = create_engine(SQLALCHEMY_DATABASE_URL)



def run_sql():

    sql = "ALTER TABLE `hoja_de_c__lculo_sin_t__tulo` MODIFY COLUMN `NUMERO` INT AUTO_INCREMENT PRIMARY KEY;"

    print(f"Ejecutando SQL: {sql}")

    try:

        with engine.connect() as connection:

            connection.execute(text(sql))

            connection.commit()

            print("¡Comando ejecutado exitosamente!")

    except Exception as e:

        print(f"Error al ejecutar SQL: {e}")



if __name__ == "__main__":

    run_sql()


from sqlalchemy import create_engine, text



SQLALCHEMY_DATABASE_URL = "mysql+pymysql://root:@localhost/opsatel"

engine = create_engine(SQLALCHEMY_DATABASE_URL)



def check_empty():

    try:

        with engine.connect() as connection:

            result = connection.execute(text("SELECT COUNT(*) FROM `hoja_de_c__lculo_sin_t__tulo` WHERE `NUMERO` = '' OR `NUMERO` IS NULL"))

            count = result.fetchone()[0]

            print(f"Filas con NUMERO vacío o nulo: {count}")

            

            result = connection.execute(text("SELECT `NUMERO` FROM `hoja_de_c__lculo_sin_t__tulo` ORDER BY `NUMERO` DESC LIMIT 5"))

            for row in result:

                print(row)

    except Exception as e:

        print(f"Error: {e}")



if __name__ == "__main__":

    check_empty()


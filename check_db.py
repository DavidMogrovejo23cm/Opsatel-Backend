from sqlalchemy import create_engine, text



SQLALCHEMY_DATABASE_URL = "mysql+pymysql://root:@localhost/opsatel"

engine = create_engine(SQLALCHEMY_DATABASE_URL)



def check_structure():

    print("Obteniendo estructura de la tabla 'hoja_de_c__lculo_sin_t__tulo'...")

    try:

        with engine.connect() as connection:

            result = connection.execute(text("DESCRIBE `hoja_de_c__lculo_sin_t__tulo`"))

            for row in result:

                print(row)

    except Exception as e:

        print(f"Error: {e}")



if __name__ == "__main__":

    check_structure()


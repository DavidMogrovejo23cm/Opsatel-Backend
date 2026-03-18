from sqlalchemy import create_engine, text



SQLALCHEMY_DATABASE_URL = "mysql+pymysql://root:@localhost/opsatel"

engine = create_engine(SQLALCHEMY_DATABASE_URL)



def read_first_row():

    try:

        with engine.connect() as connection:

            result = connection.execute(text("SELECT * FROM `hoja_de_c__lculo_sin_t__tulo` LIMIT 1"))

            for row in result:

                print(row)

    except Exception as e:

        print(f"Error: {e}")



if __name__ == "__main__":

    read_first_row()

